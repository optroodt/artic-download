import argparse
import asyncio
import io
import logging
import math
import pathlib
import sys
import typing

import bs4
import httpx
import urlobject
from PIL import Image

BLOCK_SIZE = 256
PER_REQUEST_DELAY_SECONDS = 0.2
SLEEP_DELAY_ON_ERROR_SECONDS = 180
DEFAULT_WORKER_TASK_COUNT = 2

# setup the logger
logger = logging.getLogger()
logger.setLevel(logging.INFO)
handler = logging.StreamHandler(sys.stdout)
logger.addHandler(handler)


def get_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    parser.add_argument("--workers", default=DEFAULT_WORKER_TASK_COUNT, type=int)
    parser.add_argument("--format", default="jpg", choices=["jpg", "png"])
    return parser.parse_args()


def generate_blocks(
        width: int, height: int, block_size: int
) -> typing.MutableSequence[typing.Tuple[int, int, int, int]]:
    """
    Create a list of blocks defined by their x, y position and the dimensions of the block.

    :param width: width of the image
    :param height: height of the image
    :param block_size: width and height of a single (square) block
    :return:
    """
    blocks = []

    # these are the regular blocks
    for j in range(height // block_size):
        y = block_size * j
        for i in range(math.ceil(width / block_size)):
            x = block_size * i
            blocks.append((x, y, block_size, block_size))
        tup = blocks.pop()
        # right edge might be smaller
        blocks.append((tup[0], tup[1], width - tup[0], block_size))

    # bottom row might be smaller too
    y = block_size * (j + 1)
    block_size_height = height - y
    for i in range(math.ceil(width / block_size)):
        x = block_size * i
        blocks.append((x, y, block_size, block_size_height))
    tup = blocks.pop()
    blocks.append((tup[0], tup[1], width - tup[0], block_size_height))
    logger.info(f"Generated {len(blocks)} blocks, last block: {blocks[-1]}")
    return blocks


def generate_url(
        x_pos: int, y_pos: int, x_size: int, y_size: int, base_url: urlobject.URLObject
) -> urlobject.URLObject:
    """
    Generate url for a specific block. The urls look like this

    https://www.artic.edu/iiif/2/831a05de-d3f6-f4fa-a460-23008dd58dda/0,0,256,256/256,/0/default.jpg

    The last image is not full width/height
    https://www.artic.edu/iiif/2/831a05de-d3f6-f4fa-a460-23008dd58dda/10752,0,65,256/65,/0/default.jpg

    :param x_pos:
    :param y_pos:
    :param x_size:
    :param y_size:
    :param base_url:
    :return: urlobject.URLObject
    """

    obj = base_url
    path = obj.path.split("/")

    path.extend(
        [f"{x_pos},{y_pos},{x_size},{y_size}", f"{x_size},", "0", "default.jpg"]
    )  # don't know what the 0 means (maybe a filter?)

    new_url = obj.with_path("/".join(path))
    return new_url


def extract_data(url: str) -> (int, int, urlobject.URLObject, pathlib.Path):
    """
    Extract metadata from url

    :param url: url to extract metadata from
    :return:  width, height, urlobject, filename
    """
    response = httpx.get(url)

    if response.status_code != 200:
        raise Exception(f"Did not receive a HTTP 200 ({response.status_code})")

    soup = bs4.BeautifulSoup(response.text, "lxml")
    buttons = soup.find_all("button", attrs={"data-gallery-img-width": True})

    button = buttons[-1]

    image_width = int(button["data-gallery-img-width"])
    image_height = int(button["data-gallery-img-height"])
    download_name = pathlib.Path(button["data-gallery-img-download-name"])
    # looks something like https://www.artic.edu/iiif/2/831a05de-d3f6-f4fa-a460-23008dd58dda
    base_url = urlobject.URLObject(button["data-gallery-img-iiifid"])

    response = httpx.get(base_url.add_path_segment("info.json"))
    data = response.json()
    logger.info(
        f"{data['width']} x {data['height']}, supported formats: {data['profile'][1]['formats']}"
    )
    return image_width, image_height, base_url, download_name


async def worker(
        worker_name: str, queue: asyncio.queues.Queue, out_queue: asyncio.queues.Queue
) -> None:
    # create a single client per worker
    client = httpx.AsyncClient()
    while True:
        try:
            x_pos, y_pos, x_size, y_size, base_url = queue.get_nowait()
            await asyncio.sleep(0.1)
        except asyncio.QueueEmpty:
            await client.aclose()
            break

        img_url: urlobject.URLObject = generate_url(
            x_pos, y_pos, x_size, y_size, base_url
        )

        image_bytes = io.BytesIO()
        while True:
            async with client.stream("GET", img_url) as response:
                if response.status_code != 200:
                    logger.info(
                        f"Sleeping for {SLEEP_DELAY_ON_ERROR_SECONDS} seconds due to rate-limiting ({worker_name})"
                    )
                    await asyncio.sleep(SLEEP_DELAY_ON_ERROR_SECONDS)
                    continue

                async for chunk in response.aiter_bytes():
                    image_bytes.write(chunk)
                break

        await out_queue.put((x_pos, y_pos, image_bytes))

        qsize = out_queue.qsize()
        if qsize % 100 == 0:
            logger.info(f"Downloaded {qsize} image parts...")

        # Notify the queue that the "work item" has been processed.
        queue.task_done()


async def main(url: str, workers: int, file_format: str) -> None:
    max_width, max_height, base_url, download_name = extract_data(url)
    logger.info(f"Starting download of {download_name} ({file_format})")
    logger.info(f"Hi-res image is {max_width}x{max_height}. {base_url}")

    # Create a queue that we will use to store our workload.
    queue = asyncio.Queue()
    out_queue = asyncio.Queue()

    blocks = generate_blocks(max_width, max_height, BLOCK_SIZE)
    logger.info(f"Need to download {len(blocks)} image parts...")

    for x_pos, y_pos, x_size, y_size in blocks:
        queue.put_nowait((x_pos, y_pos, x_size, y_size, base_url))

    # Create some worker tasks to process the queue concurrently.
    tasks = []
    logger.info(f"Creating {workers} workers")
    for i in range(workers):
        task = asyncio.create_task(worker(f"worker-{i}", queue, out_queue))
        tasks.append(task)

    logger.info("Waiting for download to finish...")
    await queue.join()

    # Cancel worker tasks.
    for task in tasks:
        task.cancel()

    # Wait until all worker tasks are cancelled.
    await asyncio.gather(*tasks, return_exceptions=True)

    # Create the destination image
    logger.info(f"Stitching {len(blocks)} parts together to create final image")
    destination = Image.new("RGB", (max_width, max_height))

    while True:
        # Paste all image blocks into the final image based on their x, y offset
        x_pos, y_pos, image_bytes = await out_queue.get()
        destination.paste(Image.open(image_bytes), (x_pos, y_pos))
        out_queue.task_done()

        if out_queue.empty():
            break

    logger.info(f"Saving final image {download_name}")
    if not download_name.suffix == ".jpg":
        download_name = download_name.with_suffix(".jpg")

    final_path = "output" / download_name
    destination.save(final_path)


if __name__ == "__main__":
    args = get_arguments()
    asyncio.run(main(args.url, args.workers, args.format))

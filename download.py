import argparse
import asyncio
import io
import math
import pathlib
import time
import typing

import bs4
import httpx
import requests
import urlobject
from PIL import Image

BLOCK_SIZE = 256
PER_REQUEST_DELAY_SECONDS = 0.2
SLEEP_DELAY_ON_ERROR_SECONDS = 180
DEFAULT_WORKER_TASK_COUNT = 2


def get_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    parser.add_argument("--workers", default=DEFAULT_WORKER_TASK_COUNT, type=int)
    parser.add_argument("--format", default="jpg", choices=["jpg", "png"])
    return parser.parse_args()


def download_image(
        x_pos: int, y_pos: int, x_size: int, y_size: int, base_url
) -> io.BytesIO:
    download_url: urlobject.URLObject = generate_url(
        x_pos, y_pos, x_size, y_size, base_url
    )

    # TODO: replace with httpx and async routines
    image_bytes = io.BytesIO()
    with requests.get(download_url, stream=True) as r:
        r.raise_for_status()
        for chunk in r.iter_content(chunk_size=8192):
            image_bytes.write(chunk)

    return image_bytes


def generate_blocks(
        width: int, height: int, block_size: int
) -> typing.MutableSequence[typing.Tuple[int, int, int, int]]:
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
    print(f"Generated {len(blocks)} blocks, last block: {blocks[-1]}")
    return blocks


def download_hires_image(url: str) -> pathlib.Path:
    # https://www.artic.edu/iiif/2/831a05de-d3f6-f4fa-a460-23008dd58dda
    max_width, max_height, base_url, download_name = extract_data(url)
    print(f"Starting download of {download_name}")
    print(f"Hi-res image is {max_width}x{max_height}. {base_url}")

    # this would allow massive parallelization
    blocks = generate_blocks(max_width, max_height, BLOCK_SIZE)
    destination = Image.new("RGB", (max_width, max_height))

    for i, (x_pos, y_pos, x_size, y_size) in enumerate(blocks, start=1):
        try:
            image_bytes = download_image(x_pos, y_pos, x_size, y_size, base_url)
        except requests.exceptions.HTTPError as e:
            print("Caught exception, sleeping for 10 seconds before trying again...")
            time.sleep(10)
            image_bytes = download_image(x_pos, y_pos, x_size, y_size, base_url)

        destination.paste(Image.open(image_bytes), (x_pos, y_pos))
        if i % 50 == 0:
            print(f"Downloaded {i}/{len(blocks)} image parts...")
    print(f"Finished downloading {i}/{len(blocks)} image parts!")

    print(f"Saving final image {download_name}")
    if not download_name.suffix == ".jpg":
        download_name = download_name.with_suffix(".jpg")

    final_path = "output" / download_name

    destination.save(final_path)
    return final_path


def generate_url(
        x_pos: int, y_pos: int, x_size: int, y_size: int, base_url: urlobject.URLObject
):
    # https://www.artic.edu/iiif/2/831a05de-d3f6-f4fa-a460-23008dd58dda/0,0,256,256/256,/0/default.jpg
    # last image is not full width
    # https://www.artic.edu/iiif/2/831a05de-d3f6-f4fa-a460-23008dd58dda/10752,0,65,256/65,/0/default.jpg
    obj = base_url
    path = obj.path.split("/")

    path.extend(
        [f"{x_pos},{y_pos},{x_size},{y_size}", f"{x_size},", "0", "default.jpg"]
    )

    new_url = obj.with_path("/".join(path))
    return new_url


def extract_data(url: str) -> (int, int, urlobject.URLObject, pathlib.Path):
    """
    Extract metadata from url

    :param url: url to extract metadata from
    :return:  width, height, urlobject, filename
    """
    response = requests.get(url)
    if response.status_code != 200:
        raise Exception(f"Did not receive a HTTP 200 ({response.status_code})")

    soup = bs4.BeautifulSoup(response.text, "lxml")
    buttons = soup.find_all("button", attrs={"data-gallery-img-width": True})

    button = buttons[-1]

    image_width = int(button["data-gallery-img-width"])
    image_height = int(button["data-gallery-img-height"])
    download_name = pathlib.Path(button["data-gallery-img-download-name"])
    base_url = urlobject.URLObject(button["data-gallery-img-iiifid"])

    response = requests.get(base_url.add_path_segment("info.json"))
    data = response.json()
    print(data["width"], data["height"], data["profile"][1]["formats"])
    return image_width, image_height, base_url, download_name


async def worker(name, queue, out_queue):
    # create a single client per worker
    client = httpx.AsyncClient()
    while True:
        try:
            x_pos, y_pos, x_size, y_size, base_url = await queue.get()
            await asyncio.sleep(0.1)
        except:
            await client.aclose()
            break

        img_url: urlobject.URLObject = generate_url(
            x_pos, y_pos, x_size, y_size, base_url
        )

        image_bytes = io.BytesIO()
        while True:
            async with client.stream("GET", img_url) as response:
                if response.status_code != 200:
                    print(f"Sleeping for {SLEEP_DELAY_ON_ERROR_SECONDS} seconds")
                    await asyncio.sleep(20)
                    continue

                async for chunk in response.aiter_bytes():
                    image_bytes.write(chunk)
                break

        await out_queue.put((x_pos, y_pos, image_bytes))

        qsize = out_queue.qsize()
        if qsize % 100 == 0:
            print(f"Downloaded {qsize} image parts...")

        # Notify the queue that the "work item" has been processed.
        queue.task_done()


async def main(url: str, workers: int, file_format: str) -> None:
    # https://www.artic.edu/iiif/2/831a05de-d3f6-f4fa-a460-23008dd58dda
    max_width, max_height, base_url, download_name = extract_data(url)
    print(f"Starting download of {download_name} ({file_format})")
    print(f"Hi-res image is {max_width}x{max_height}. {base_url}")

    # Create a queue that we will use to store our workload.
    queue = asyncio.Queue()
    out_queue = asyncio.Queue()

    blocks = generate_blocks(max_width, max_height, BLOCK_SIZE)
    print(f"Need to download {len(blocks)} image parts...")

    for x_pos, y_pos, x_size, y_size in blocks:
        queue.put_nowait((x_pos, y_pos, x_size, y_size, base_url))

    # Create some worker tasks to process the queue concurrently.
    tasks = []
    print(f"Creating {workers} workers")
    for i in range(workers):
        task = asyncio.create_task(worker(f"worker-{i}", queue, out_queue))
        tasks.append(task)

    await queue.join()

    # Cancel our worker tasks.
    for task in tasks:
        task.cancel()

    # Wait until all worker tasks are cancelled.
    await asyncio.gather(*tasks, return_exceptions=True)
    print(f"Stitching {len(blocks)} parts together to create final image")
    destination = Image.new("RGB", (max_width, max_height))

    while True:
        x_pos, y_pos, image_bytes = await out_queue.get()
        destination.paste(Image.open(image_bytes), (x_pos, y_pos))
        out_queue.task_done()
        if out_queue.empty():
            break

    print(f"Saving final image {download_name}")
    if not download_name.suffix == ".jpg":
        download_name = download_name.with_suffix(".jpg")

    final_path = "output" / download_name
    destination.save(final_path)


if __name__ == "__main__":
    args = get_arguments()
    asyncio.run(main(args.url, args.workers, args.format))
    # test_url = "https://www.artic.edu/artworks/111628/nighthawks"
    # download_hires_image(args.url)

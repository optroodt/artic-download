import argparse
import math
import os
import time

import bs4
import requests
from PIL import Image
from urlobject import URLObject

BLOCK_SIZE = 256

"""
<button
                            data-gallery-img-src="data:image/gif;base64,R0lGODlhCQAFAPUAABggIBwlJRwoKB0oKR0uNRwuOSAmJCooIy8qIy4uJiYrKScvLi0uKDguJTsvJS0wJyM1LzkxJjA0LSQzMC42MSs1NSg7N0MzJkA4K0A+NTFAOzJDPDFCPkFEPytEQzxNSENRSkdWSklcTk1dUVZkVVRqW3aRenmUfKufaH+bgba3h7y8iMG9hwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAACH5BAAAAAAALAAAAAAJAAUAAAYqwMbFgUg8JIuKgkGxcD6kFSsA0HgIhY4KBRqFIIZDJIM5pUwl0WYiGAQBADs="
                                        data-gallery-img-srcset="https://www.artic.edu/iiif/2/831a05de-d3f6-f4fa-a460-23008dd58dda/full/200,/0/default.jpg 200w, https://www.artic.edu/iiif/2/831a05de-d3f6-f4fa-a460-23008dd58dda/full/400,/0/default.jpg 400w, https://www.artic.edu/iiif/2/831a05de-d3f6-f4fa-a460-23008dd58dda/full/843,/0/default.jpg 843w"
                                        data-gallery-img-width="10817"
                                        data-gallery-img-height="5912"
                                        data-gallery-img-credit=""
                                                    data-gallery-img-share-url="#"
                                                    data-gallery-img-download-url="https://www.artic.edu/iiif/2/831a05de-d3f6-f4fa-a460-23008dd58dda/full/!3000,3000/0/default.jpg"
                                        data-gallery-img-download-name="1942.51 - Nighthawks.jpg"
                                        data-gallery-img-iiifId="https://www.artic.edu/iiif/2/831a05de-d3f6-f4fa-a460-23008dd58dda"
                        data-gtm-event=""
            data-gtm-event-category="in-page"
            aria-label="show alternative image"
            disabled
"""


def get_arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    return parser.parse_args()


def download_file(x_pos, y_pos, x_size, y_size, base_url):
    # TODO: ideally this would not write to disk but just keep chunk in memory
    # NOTE the stream=True parameter below
    download_url = generate_url(x_pos, y_pos, x_size, y_size, base_url)
    uuid = URLObject(base_url).path.split("/")[-1].split("-")[0]
    local_filename = f"images/{uuid}_{x_pos}x{y_pos}.jpg"
    # TODO: replace with httpx and async routines
    with requests.get(download_url, stream=True) as r:
        r.raise_for_status()
        with open(local_filename, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                # If you have chunk encoded response uncomment if
                # and set chunk_size parameter to None.
                # if chunk:
                f.write(chunk)
    # TODO: this should become a Path object
    return local_filename


def generate_blocks(width, height, block_size):
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


def download_hires_image(url):
    # https://www.artic.edu/iiif/2/831a05de-d3f6-f4fa-a460-23008dd58dda
    max_width, max_height, base_url, download_name = extract_data(url)
    print(f"Starting download of {download_name}")
    print(f"Hi-res image is {max_width}x{max_height}. {base_url}")

    # this would allow massive parallelization
    blocks = generate_blocks(max_width, max_height, BLOCK_SIZE)
    destination = Image.new("RGB", (max_width, max_height))

    for i, (x_pos, y_pos, x_size, y_size) in enumerate(blocks, start=1):
        try:
            local_filename = download_file(x_pos, y_pos, x_size, y_size, base_url)
        except requests.exceptions.HTTPError as e:
            print("Caught exception, sleeping for 10 seconds before trying again...")
            time.sleep(10)
            local_filename = download_file(x_pos, y_pos, x_size, y_size, base_url)

        destination.paste(Image.open(local_filename), (x_pos, y_pos))
        os.unlink(local_filename)
        if i % 50 == 0:
            print(f"Downloaded {i}/{len(blocks)} image parts...")
    print(f"Finished downloading {i}/{len(blocks)} image parts!")

    print(f"Saving final image {download_name}")
    if not download_name.endswith(".jpg"):
        download_name += ".jpg"
    # TODO: make this a path
    destination.save("output/" + download_name)


def generate_url(x_pos, y_pos, x_size, y_size, base_url):
    # https://www.artic.edu/iiif/2/831a05de-d3f6-f4fa-a460-23008dd58dda/0,0,256,256/256,/0/default.jpg

    # last image is not full width
    # https://www.artic.edu/iiif/2/831a05de-d3f6-f4fa-a460-23008dd58dda/10752,0,65,256/65,/0/default.jpg
    obj = URLObject(base_url)
    path = obj.path.split("/")

    path.extend([f"{x_pos},{y_pos},{x_size},{y_size}", f"{x_size},", "0", "default.jpg"])

    new_url = obj.with_path("/".join(path))
    return new_url


def extract_data(url):
    response = requests.get(url)
    soup = bs4.BeautifulSoup(response.text, "lxml")
    buttons = soup.find_all("button", attrs={"data-gallery-img-width": True})
    # print(buttons)
    # assert len(buttons) == 1, "Found more than 1 matching tags"
    button = buttons[-1]
    image_width = int(button["data-gallery-img-width"])
    image_height = int(button["data-gallery-img-height"])

    download_name = button["data-gallery-img-download-name"]
    base_url = button["data-gallery-img-iiifid"]

    # title in <h1 class="sr-only">
    # "data-gallery-img-height="5912" data-gallery-img-iiifid"
    return image_width, image_height, base_url, download_name


if __name__ == "__main__":
    args = get_arguments()
    # test_url = "https://www.artic.edu/artworks/111628/nighthawks"
    download_hires_image(args.url)

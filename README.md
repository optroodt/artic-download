# artic-download
Download hi-res images from the Art Institute Chicago.

As far as I'm aware, works of art cannot easily be downloaded in their highest resolution as a single file. Therefor 
you need to download hundreds or thousands of smaller tiles and stitch them together to make a single image. 

The script uses httpx to download images async and multiple workers to do it concurrently.

## Usage

First install the requirements:
```commandline
pip install -r requirements.txt
```

Find an image you like from the [Art Institure Chicago](https://www.artic.edu/collection) and download it!

```commandline
python download "https://www.artic.edu/artworks/111628/nighthawks"
```
The image will be downloaded into `output/`

## TODO
- support downloading supported file formats other than jpg (e.g. png, tif)
- clean up the code :)

## Notes
Sample element from which we can extract key data
```
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
```

More metadata can be found in 
```commandline
https://www.artic.edu/iiif/2/f95a0a70-90c5-2806-2a66-68f27f8c0735/info.json
```

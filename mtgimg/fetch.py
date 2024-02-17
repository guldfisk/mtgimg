import requests
from mtgorp.models.persistent.attributes.layout import Layout
from PIL import Image

from mtgimg.interface import ImageFetchException, ImageRequest, SizeSlug


def get_scryfall_image(image_request: ImageRequest) -> Image.Image:
    try:
        remote_card_response = requests.get(image_request.remote_card_uri, timeout=32)
    except Exception as e:
        raise ImageFetchException(e)

    if not remote_card_response.ok:
        raise ImageFetchException(remote_card_response.status_code)

    remote_card = remote_card_response.json()

    try:
        if image_request.pictured.cardboard.layout == Layout.MELD and image_request.back:
            for part in remote_card["all_parts"]:
                if part["name"] == image_request.pictured.cardboard.back_card.name:
                    remote_card = requests.get(part["uri"], timeout=32).json()

        image_response = requests.get(
            remote_card["card_faces"][-1 if image_request.back else 0]["image_uris"]["png"]
            if image_request.pictured.cardboard.layout in (Layout.TRANSFORM, Layout.MODAL)
            else remote_card["image_uris"]["png"],
            stream=True,
            timeout=30,
        )

    except Exception as e:
        raise ImageFetchException(e)

    if not image_response.ok:
        raise ImageFetchException(remote_card_response.status_code)

    fetched_image = Image.open(image_response.raw)
    fetched_image.load()

    if fetched_image.size != SizeSlug.ORIGINAL.get_size():
        fetched_image = fetched_image.resize(SizeSlug.ORIGINAL.get_size(), Image.LANCZOS)

    return fetched_image

from __future__ import annotations

from functools import lru_cache

from PIL import Image

from mtgimg import crop as image_crop
from mtgimg import paths
from mtgimg.interface import ImageLoader, SizeSlug, ImageFetchException, resize_image


class BaseImageLoader(ImageLoader):

    _size_cardback_path_map = {
        SizeSlug.ORIGINAL: paths.CARD_BACK_PATH,
        SizeSlug.MEDIUM: paths.MEDIUM_CARD_BACK_PATH,
        SizeSlug.SMALL: paths.SMALL_CARD_BACK_PATH,
        SizeSlug.THUMBNAIL: paths.THUMBNAIL_CARD_BACK_PATH,
    }

    @lru_cache(maxsize = None)
    def get_default_image(self, size_slug: SizeSlug = SizeSlug.ORIGINAL, crop: bool = False) -> Image.Image:
        if crop:
            cropped = image_crop.crop(
                self.load_image_from_disk(
                    self._size_cardback_path_map[SizeSlug.ORIGINAL]
                )
            )
            if size_slug != size_slug.ORIGINAL:
                cropped = resize_image(
                    cropped,
                    size_slug,
                    True,
                )
            return cropped

        try:
            return self.load_image_from_disk(
                self._size_cardback_path_map[size_slug]
            )
        except ImageFetchException:
            resized_back = resize_image(
                self.load_image_from_disk(
                    self._size_cardback_path_map[SizeSlug.ORIGINAL]
                ),
                size_slug,
                False,
            )
            with open(self._size_cardback_path_map[size_slug], 'wb') as f:
                resized_back.save(f)

            return resized_back

import typing as t

import os, copy
from enum import Enum
from abc import ABC, abstractmethod
from functools import lru_cache

from PIL import Image
from promise import Promise
from lazy_property import LazyProperty
from frozendict import frozendict

from mtgorp.models.persistent.printing import Printing
from mtgimg import paths


class SizeSlug(Enum):
    ORIGINAL = '', 1
    MEDIUM = 'm', .5
    SMALL = 's', .3
    THUMBNAIL = 't', .15

    @property
    def code(self) -> str:
        return self._code

    @property
    def scale(self) -> float:
        return self._scale

    def get_size(self, cropped: bool = False):
        return IMAGE_SIZE_MAP[frozenset((self, cropped))]

    def __new__(cls, code, scale):
        obj = object.__new__(cls)
        obj._code = code
        obj._scale = scale
        return obj


IMAGE_SIZE_MAP = {
    frozenset((SizeSlug.ORIGINAL, False)): (745, 1040),
    frozenset((SizeSlug.ORIGINAL, True)): (560, 435),
}

IMAGE_SIZE_MAP.update(
    {
        frozenset((size_slug, crop)):
            tuple(
                int(dimension * size_slug.scale)
                for dimension in
                IMAGE_SIZE_MAP[frozenset((SizeSlug.ORIGINAL, crop))]
            )
        for size_slug in
        SizeSlug
        for crop in
        (True, False)
    }
)

IMAGE_SIZE_MAP = frozendict(IMAGE_SIZE_MAP)


class ImageFetchException(Exception):
    pass


class Imageable(ABC):

    @abstractmethod
    def get_image(
        self,
        size: t.Tuple[int, int],
        loader: 'ImageLoader',
        back: bool = False,
        crop: bool = False,
    ) -> Image.Image:
        pass

    @abstractmethod
    def get_image_name(self, back: bool = False, crop: bool = False) -> str:
        pass

    @classmethod
    @abstractmethod
    def get_image_dir_name(cls) -> str:
        pass

    @abstractmethod
    def has_back(self) -> bool:
        pass

    @abstractmethod
    def __hash__(self) -> int:
        pass


pictureable = t.Union[Imageable, Printing]


class ImageRequest(object):

    def __init__(
        self,
        pictured: t.Optional[pictureable] = None,
        *,
        pictured_type: t.Union[t.Type[Printing], t.Type[Imageable]] = Printing,
        picture_name: t.Optional[str] = None,
        back: bool = False,
        crop: bool = False,
        size_slug: SizeSlug = SizeSlug.ORIGINAL,
        save: bool = True,
        cache_only: bool = False,
    ):
        self._pictured = pictured
        self._pictured_type = pictured_type
        self._pictured_name = picture_name if isinstance(picture_name, (str, type(None))) else str(picture_name)
        self._back = back
        self._crop = crop
        self._size_slug = size_slug
        self._save = save
        self._cache_only = cache_only

    @property
    def has_image(self) -> bool:
        if self._pictured_name is not None:
            return True

        if self._back:
            if isinstance(self._pictured, Imageable):
                return self._pictured.has_back()
            return bool(self._pictured.cardboard.back_cards)

        if isinstance(self._pictured, Imageable):
            return True
        return bool(self._pictured.cardboard.front_cards)

    @property
    def _identifier(self) -> str:
        if self._pictured_name is not None:
            return self._pictured_name

        return (
            self._pictured.get_image_name()
            if isinstance(self._pictured, Imageable) else
            str(self._pictured.id)
        )

    @property
    def _name_no_extension(self) -> str:
        return (
            self._identifier + (
                '_b'
                if self._back else
                ''
            )
            if self.has_image else
            'cardback'
        ) + (
            '_crop'
            if self._crop else
            ''
        ) + (
            '_' + self._size_slug.code
            if self.size_slug.code else
            ''
        )

    @property
    def name(self) -> str:
        return self._name_no_extension + '.' + self.extension

    @property
    def extension(self) -> str:
        return 'png'

    @classmethod
    def _get_imageable_dir_path(cls, imageable: t.Union[Imageable, t.Type[Imageable]]) -> str:
        return os.path.join(
            paths.IMAGES_PATH,
            '_' + imageable.get_image_dir_name(),
        )

    @property
    def dir_path(self) -> str:
        if self._pictured_name is not None:
            if issubclass(self._pictured_type, Imageable):
                return self._get_imageable_dir_path(
                    self._pictured_type
                )
            return paths.IMAGES_PATH

        if self.has_image:
            if isinstance(self._pictured, Imageable):
                return self._get_imageable_dir_path(
                    self._pictured
                )
            return paths.IMAGES_PATH

        return paths.CARD_BACK_DIRECTORY_PATH

    @property
    def path(self) -> str:
        return os.path.join(
            self.dir_path,
            self.name,
        )

    @LazyProperty
    def remote_card_uri(self) -> str:
        return f'https://api.scryfall.com/cards/multiverse/{self.pictured.id}'

    @property
    def pictured(self) -> pictureable:
        return self._pictured

    @property
    def back(self) -> bool:
        return self._back

    @property
    def crop(self) -> bool:
        return self._crop

    @property
    def size_slug(self) -> SizeSlug:
        return self._size_slug

    @property
    def size(self) -> t.Tuple[int, int]:
        return IMAGE_SIZE_MAP[
            frozenset(
                (self._size_slug, self._crop)
            )
        ]

    @property
    def save(self) -> bool:
        return self._save

    @property
    def cache_only(self) -> bool:
        return self._cache_only

    @property
    def pictured_name(self) -> t.Optional[str]:
        return self._pictured_name

    @property
    def pictured_type(self) -> t.Union[t.Type[Printing], t.Type[Imageable]]:
        return self._pictured_type

    def spawn(self, **kwargs) -> 'ImageRequest':
        _image_request = copy.copy(self)
        _image_request.__dict__.update(
            {
                '_' + key: value
                for key, value in
                kwargs.items()
            }
        )
        return _image_request

    def __hash__(self) -> int:
        return hash(
            (
                self._pictured,
                self._pictured_type,
                self._pictured_name,
                self._back,
                self._crop,
                self._size_slug,
                self._save,
                self._cache_only,
            )
        )

    def __eq__(self, other) -> bool:
        return (
            isinstance(other, self.__class__)
            and self._pictured == other._pictured
            and self._pictured_type == other._pictured_type
            and self._pictured_name == other._pictured_name
            and self._back == other._back
            and self._crop == other._crop
            and self._size_slug == other._size_slug
            and self._save == other._save
            and self._cache_only == other._cache_only
        )

    def __repr__(self) -> str:
        if self._pictured_name is not None:
            return '{}({}, {})'.format(
                self.__class__.__name__,
                self._pictured_type,
                self._pictured_name,
            )

        return '{}({}, {}, {}, {}, {}, {})'.format(
            self.__class__.__name__,
            self._pictured,
            self._back,
            self._crop,
            self._size_slug,
            self._save,
            self._cache_only,
        )


class ImageLoader(ABC):

    @abstractmethod
    def get_image(
        self,
        pictured: pictureable = None,
        *,
        pictured_type: t.Union[t.Type[Printing], t.Type[Imageable]] = Printing,
        picture_name: t.Optional[str] = None,
        back: bool = False,
        crop: bool = False,
        size_slug: SizeSlug = SizeSlug.ORIGINAL,
        save: bool = True,
        cache_only: bool = False,
        image_request: ImageRequest = None,
    ) -> Promise:
        pass

    @abstractmethod
    def get_default_image(self, size_slug: SizeSlug = SizeSlug.ORIGINAL) -> Image.Image:
        pass

    @lru_cache(maxsize=256)
    def open_image(self, path: str) -> Image.Image:
        try:
            image = Image.open(path)
            image.load()
            return image
        except Exception as e:
            raise ImageFetchException(e)

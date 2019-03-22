import typing as t

import os
from concurrent.futures import Executor, ThreadPoolExecutor
from threading import Lock, Event
import functools

import requests as r
from PIL import Image
from promise import Promise

from mtgorp.models.persistent.attributes.layout import Layout

from mtgimg import paths
from mtgimg.interface import ImageRequest, Imageable, ImageLoader, picturable
from mtgimg import crop as image_crop


IMAGE_SIZE = (745, 1040)
CROPPED_IMAGE_SIZE = (560, 435)

IMAGE_WIDTH, IMAGE_HEIGHT = IMAGE_SIZE

CROPPED_IMAGE_WIDTH, CROPPED_IMAGE_HEIGHT = CROPPED_IMAGE_SIZE

T = t.TypeVar('T')


class EventWithValue(Event, t.Generic[T]):

	def __init__(self) -> None:
		super().__init__()
		self.value = None #type: t.Optional[T]

	def set_value(self, value: T) -> None:
		self.value = value
		super().set()

	def set(self) -> None:
		raise NotImplemented()


class TaskAwaiter(t.Generic[T]):

	def __init__(self):
		self._lock = Lock()
		self._map = dict() #type: t.Dict[ImageRequest, EventWithValue[T]]

	def resolve(self, image_request: ImageRequest):
		del self._map[image_request]

	def get_condition(self, image_request: ImageRequest) -> t.Tuple[EventWithValue[T], bool]:
		with self._lock:
			try:
				return self._map[image_request], True
			except KeyError:
				self._map[image_request] = event = EventWithValue()
				return event, False


class ImageFetchException(Exception):
	pass


class _ImageableProcessor(object):
	_processing = TaskAwaiter() #type: TaskAwaiter[Image.Image]

	@classmethod
	def _save_imageable(
		cls,
		image_request: ImageRequest,
		size: t.Tuple[int, int],
		loader: ImageLoader,
		event: EventWithValue[Image.Image],
	) -> Image.Image:

		image = image_request.pictured.get_image(
			size,
			loader,
			image_request.back,
			image_request.crop,
		)

		if image.size != size:
			image = image.resize(size)

		if image_request.save:
			if not os.path.exists(image_request.dir_path):
				os.makedirs(image_request.dir_path)

			image.save(image_request.path)

		event.set_value(image)

		return image

	@classmethod
	def get_image(cls, image_request: ImageRequest, loader: ImageLoader):
		try:
			return loader.open_image(image_request.path)
		except FileNotFoundError:
			pass

		event, in_progress = cls._processing.get_condition(image_request)

		if in_progress:
			event.wait()
			return event.value

		return cls._save_imageable(
			image_request,
			CROPPED_IMAGE_SIZE if image_request.crop else IMAGE_SIZE,
			loader,
			event,
		)


class _Fetcher(object):
	_fetching = TaskAwaiter() #type: TaskAwaiter[Image.Image]
	_size = IMAGE_SIZE

	@classmethod
	def _fetch_image(cls, event: EventWithValue[Image.Image], image_request: ImageRequest):
		try:
			remote_card_response = r.request('GET', image_request.remote_card_uri, timeout = 30)
		except Exception as e:
			raise ImageFetchException(e)

		if not remote_card_response.ok:
			raise ImageFetchException(remote_card_response.status_code)
		
		remote_card = remote_card_response.json()

		try:
			if image_request.pictured.cardboard.layout == Layout.MELD and image_request.back:
				for part in remote_card['all_parts']:
					if part['name'] == image_request.pictured.cardboard.back_card.name:
						remote_card = r.request('GET', part['uri'], timeout = 30).json()

			image_response = r.request(
				'GET',
				remote_card['card_faces'][-1 if image_request.back else 0]['image_uris']['png']
				if image_request.pictured.cardboard.layout == Layout.TRANSFORM else
				remote_card['image_uris']['png'],
				stream=True,
				timeout = 30,
			)

		except Exception as e:
			raise ImageFetchException(e)

		if not image_response.ok:
			raise ImageFetchException(remote_card_response.status_code)
		
		if not os.path.exists(image_request.dir_path):
			os.makedirs(image_request.dir_path)

		temp_path = os.path.join(image_request.dir_path, '_' + image_request.name + '.' + image_request.extension)

		with open(temp_path, 'wb') as temp_file:
			for chunk in image_response.iter_content(1024):
				temp_file.write(chunk)

			with open(temp_path, 'rb') as f:
				fetched_image = Image.open(f)

			if not fetched_image.size == cls._size:
				fetched_image = fetched_image.resize(cls._size)
				fetched_image.save(
					image_request.path,
					image_request.extension,
				)
			else:
				os.rename(temp_path, image_request.path)

		return_image = Image.open(image_request.path)

		event.set_value(return_image)

		return return_image

	@classmethod
	def get_image(cls, image_request: ImageRequest, loader: ImageLoader) -> Image.Image:
		try:
			return loader.open_image(image_request.path)
		except FileNotFoundError:
			if not image_request.has_image:
				raise ImageFetchException('Missing default image')

		event, in_progress = cls._fetching.get_condition(image_request)

		if in_progress:
			event.wait()
			return event.value

		return cls._fetch_image(event, image_request)


class _Cropper(object):
	_size = CROPPED_IMAGE_SIZE
	_cropping = TaskAwaiter() #type: TaskAwaiter[Image.Image]

	@classmethod
	def _cropped_image(
		cls,
		event: EventWithValue[Image.Image],
		image: Image.Image,
		image_request: ImageRequest,
	) -> Image.Image:
		if not os.path.exists(image_request.dir_path):
			os.makedirs(image_request.dir_path)

		cropped_image = image_crop.crop(image, image_request)
		cropped_image.save(image_request.path, image_request.extension)

		event.set_value(cropped_image)

		return cropped_image

	@classmethod
	def cropped_image(cls, image_request: ImageRequest, loader: ImageLoader) -> Image.Image:
		try:
			return loader.open_image(image_request.path)
		except FileNotFoundError:
			pass

		event, in_progress = cls._cropping.get_condition(image_request)

		if in_progress:
			event.wait()
			return event.value

		return cls._cropped_image(
			event,
			_Fetcher.get_image(image_request.cropped_as(False), loader),
			image_request,
		)


class Loader(ImageLoader):

	def __init__(
		self,
		printing_executor: t.Union[Executor, int] = None,
		imageable_executor: t.Union[Executor, int] = None,
	):
		super().__init__()

		self._printings_executor = (
			printing_executor
			if printing_executor is isinstance(printing_executor, Executor) else
			ThreadPoolExecutor(
				max_workers = printing_executor if isinstance(printing_executor, int) else 10
			)
		)

		self._imageables_executor = (
			imageable_executor
			if imageable_executor is isinstance(imageable_executor, Executor) else
			ThreadPoolExecutor(
				max_workers = imageable_executor if isinstance(imageable_executor, int) else 10
			)
		)

	def get_image(
		self,
		pictured: picturable = None,
		back: bool = False,
		crop: bool = False,
		save: bool = True,
		image_request: ImageRequest = None,
	) -> Promise:
		_image_request = (
			ImageRequest(pictured, back, crop, save)
			if image_request is None else
			image_request
		)

		if isinstance(_image_request.pictured, Imageable):
			return Promise.resolve(
				self._imageables_executor.submit(
					_ImageableProcessor.get_image,
					_image_request,
					self,
				)
			)

		if _image_request.crop:
			return Promise.resolve(
				self._printings_executor.submit(
					_Cropper.cropped_image,
					_image_request,
					self,
				)
			)

		return Promise.resolve(
			self._printings_executor.submit(
				_Fetcher.get_image,
				_image_request,
				self,
			)
		)

	def get_default_image(self) -> Promise:
		return Promise.resolve(
			self._printings_executor.submit(
				lambda : self.open_image(paths.CARD_BACK_PATH)
			)
		)


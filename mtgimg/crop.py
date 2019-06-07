import typing as t

from PIL import Image

from mtgorp.models.persistent.attributes.layout import Layout
from mtgorp.models.persistent.attributes import typeline

from mtgimg.interface import ImageRequest


CROPPED_SIZE = (560, 435)


def _split_horizontal(width: int, height: int, images: t.Tuple[Image.Image, ...]):
	offset = width // len(images)

	canvas = Image.new(
		'RGBA',
		(width, height),
		(0, 0, 0, 0),
	)

	for index, image in enumerate(images):
		canvas.paste(
			image.crop((0, 0, offset, height)),
			(index*offset, 0, (index+1)*offset, height)
		)

	return canvas


def _crop_standard(image: Image.Image) -> Image.Image:
	return image.crop(
		(92, 120, 652, 555)
	)


def _crop_split(image: Image.Image) -> Image.Image:
	return _split_horizontal(
		CROPPED_SIZE[0],
		CROPPED_SIZE[1],
		tuple(
			image
				.crop(box)
				.rotate(-90, expand=1)
				.resize((650, 435), Image.LANCZOS)
			for box in
			(
				(96, 82, 345, 454),
				(96, 582, 345, 954),
			)
		),
	)


def _crop_aftermath(image: Image.Image) -> Image.Image:
	top = image.crop((92, 120, 652, 332))
	bot = image.crop((408, 590, 620, 950))

	top.paste(
		bot.rotate(90, expand=1),
		(top.width // 2, 0)
	)

	return top.resize(
		(1149, 435),
		Image.LANCZOS,
	).crop(
		(294, 0, 854, 435)
	)


def _crop_sage(image: Image.Image) -> Image.Image:
	return (
		image
			.crop((373, 115, 686, 872))
			.rotate(-90, expand=True)
			.resize(
				(1052, 435),
				Image.LANCZOS,
			)
			.crop((246, 0, 806, 435))
	)


def crop(image: Image.Image, image_request: ImageRequest) -> Image.Image:
	layout = image_request.pictured.cardboard.layout

	if layout == Layout.SAGA or typeline.SAGA in image_request.pictured.cardboard.front_card.type_line:
		return _crop_sage(image)

	if layout == Layout.STANDARD:
		return _crop_standard(image)

	if layout == Layout.SPLIT and len(image_request.pictured.cardboard.front_cards) == 2:
		return _crop_split(image)

	if layout == Layout.AFTERMATH and len(image_request.pictured.cardboard.front_cards) == 2:
		return _crop_aftermath(image)

	return _crop_standard(image)


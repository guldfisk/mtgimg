import os

from setuptools import setup

setup(
	name = 'mtgimg',
	version = '1.0',
	packages = ['mtgimg'],
	dependency_links = [
		'https://github.com/guldfisk/mtgorp/tarball/master#egg=mtgorp-1.0',
		'https://github.com/guldfisk/orp/tarball/master#egg=orp-1.0',
	],
	package_data = {
		'mtgimg': [os.path.join('mtgimg', 'cardback', 'cardback.png')],
	},
	include_package_data = True,
	install_requires = [
		'appdirs',
		'lazy-property',
		'mtgorp',
		'orp',
		'pillow',
		'requests',
		'promise',
	],
)
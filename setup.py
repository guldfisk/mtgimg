import os

from setuptools import setup

setup(
    name='mtgimg',
    version='1.0',
    packages=['mtgimg'],
    package_data={
        'mtgimg': [
            os.path.join('cardback', 'cardback.png'),
            os.path.join('cardback', 'cardback_m.png'),
            os.path.join('cardback', 'cardback_t.png'),
        ],
    },
    include_package_data=True,
    install_requires=[
        'appdirs',
        'lazy-property',
        'mtgorp @ https://github.com/guldfisk/mtgorp/tarball/master#egg=mtgorp-1.0',
        'orp @ https://github.com/guldfisk/orp/tarball/master#egg=orp-1.0',
        'pillow',
        'requests',
        'promise',
        'frozendict',
    ],
)

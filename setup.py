import os
import setuptools

metadata = {}
here = os.path.abspath(os.path.dirname(__file__))
with open(os.path.join(here, 'ssec', '__metadata__.py'), 'r', encoding='utf-8') as fh:
    exec(fh.read(), metadata)

with open('README.md', 'r', encoding='utf-8') as fh:
    long_description = fh.read()

setuptools.setup(
    name=metadata['__name__'],
    version=metadata['__version__'],
    author=metadata['__author__'],
    author_email=metadata['__author_email__'],
    description=metadata['__description__'],
    long_description=long_description,
    long_description_content_type='text/markdown',
    url='https://github.com/jbaudisch/ssec',
    license='MIT',
    project_urls={
        'Bug Tracker': 'https://github.com/jbaudisch/ssec/issues',
    },
    classifiers=[
        'Development Status :: 4 - Beta',
        'Environment :: Console',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: MIT License',
        'Natural Language :: English',
        'Operating System :: OS Independent',
        'Programming Language :: Python :: 3.10',
        'Topic :: System :: Networking'
    ],
    packages=['ssec'],
    install_requires=['requests'],
    python_requires='>=3.10',
)

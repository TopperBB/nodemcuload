from setuptools import setup

setup(
    name = "nodemcuload",
    version = "0.0.2",
    author = "Jonathan Heathcote",
    author_email = "mail@jhnet.co.uk",
    description = "NodeMCU file system utility.",
    license = "GPLv3",
    url = "https://github.com/mossblaser/nodemcuload",
    py_modules=['nodemcuload'],
    entry_points = {
        "console_scripts": [
            "nodemcuload=nodemcuload:main",
        ],
    },
    install_requires=["pyserial"],
)


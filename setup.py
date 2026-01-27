from setuptools import find_packages, setup

setup(
    name='netbox-incus-sync',
    version='0.1',
    description='Synchronisation automatique des instances Incus vers NetBox',
    install_requires=['requests-unixsocket>=0.3.0'],
    packages=find_packages(),
    include_package_data=True,
    zip_safe=False,
)
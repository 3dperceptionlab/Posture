from setuptools import setup

package_name = 'arduino_sensor'

setup(
    name=package_name,
    version='0.0.0',
    packages=[package_name],
    install_requires=['setuptools', 'pyserial'],
    zip_safe=True,
    entry_points={
        'console_scripts': [
            'sensor_node = arduino_sensor.sensor_node:main',
        ],
    },
)

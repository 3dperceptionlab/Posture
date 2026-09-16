from setuptools import setup

package_name = 'posture_table'

setup(
    name=package_name,
    version='0.1.0',
    packages=[package_name],
    data_files=[
        ('share/' + package_name, ['package.xml']),
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
    ],
    install_requires=['setuptools', 'pyserial'],
    zip_safe=True,
    author='Michael',
    author_email='',
    description='Nodo ROS 2 para leer la distancia de la mesa con Arduino',
    license='Apache-2.0',
    entry_points={
        'console_scripts': [
            'table_node = posture_table.table_node:main',
        ],
    },
)

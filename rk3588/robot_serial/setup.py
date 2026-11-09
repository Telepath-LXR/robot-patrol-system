from setuptools import setup

package_name = 'robot_serial'

setup(
    name=package_name,
    version='0.1.0',
    packages=[package_name],
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name + '/launch', ['launch/serial_bridge.launch.py']),
    ],
    install_requires=['setuptools', 'pyserial'],
    tests_require=['pytest'],
    zip_safe=True,
    maintainer='alientek',
    maintainer_email='alientek@todo.todo',
    description='RK3588 与 STM32 的串口桥接包（协议层 + 桥节点）',
    license='MIT',
    entry_points={
        'console_scripts': [
            'serial_bridge_node = robot_serial.serial_bridge_node:main',
        ],
    },
)

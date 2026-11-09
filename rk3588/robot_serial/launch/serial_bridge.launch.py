"""serial_bridge_node 的一键启动."""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    port = LaunchConfiguration('port')
    baud = LaunchConfiguration('baud')
    wheel_base = LaunchConfiguration('wheel_base')
    max_speed = LaunchConfiguration('max_wheel_speed')
    cmd_timeout = LaunchConfiguration('cmd_timeout')
    hil_mode = LaunchConfiguration('hil_mode')

    return LaunchDescription([
        DeclareLaunchArgument('port', default_value='/dev/robot_mcu',
                              description='串口设备路径'),
        DeclareLaunchArgument('baud', default_value='115200'),
        DeclareLaunchArgument('wheel_base', default_value='0.30',
                              description='轮距, 单位 m'),
        DeclareLaunchArgument('max_wheel_speed', default_value='1.0',
                              description='单轮最大线速度, 单位 m/s'),
        DeclareLaunchArgument('cmd_timeout', default_value='0.5',
                              description='/cmd_vel 超时急停阈值, 单位 s'),
        DeclareLaunchArgument('hil_mode', default_value='false',
                              description='true 时本节点退出, UART 让位给 hil_bridge'),
        Node(
            package='robot_serial',
            executable='serial_bridge_node',
            name='serial_bridge_node',
            output='screen',
            parameters=[{
                'port': port,
                'baud': baud,
                'wheel_base': wheel_base,
                'max_wheel_speed': max_speed,
                'cmd_timeout': cmd_timeout,
                'hil_mode': hil_mode,
            }],
        ),
    ])

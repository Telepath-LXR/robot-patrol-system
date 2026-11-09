import os
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource

def generate_launch_description():
    pkg_share = get_package_share_directory('patrol_description')

    # 【改】地图路径改成从包安装目录取，不再硬编码 /home/xxx 绝对路径。
    # office_map_auto 是实测可用的办公室地图；若用 patrol_world 简单世界，
    # 换成 office_map.yaml 或自己用 slam_toolbox 重新建图。
    map_file = os.path.join(pkg_share, 'maps', 'office_map_auto.yaml')

    # 路径指向你自己的 patrol_description 包
    nav2_params = os.path.join(pkg_share, 'params', 'nav2_params.yaml')

    return LaunchDescription([
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(os.path.join(
                get_package_share_directory('nav2_bringup'), 'launch', 'bringup_launch.py')),
            launch_arguments=[
                ('map', map_file),
                ('use_sim_time', 'True'),
                ('params_file', nav2_params),
                ('autostart', 'True')
            ]
        )
    ])

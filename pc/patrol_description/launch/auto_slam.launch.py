import os
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription, TimerAction
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch_ros.actions import Node

def generate_launch_description():
    # 1. 启动 SLAM Toolbox
    slam_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(os.path.join(
            get_package_share_directory('slam_toolbox'), 'launch', 'online_async_launch.py')),
        launch_arguments=[('use_sim_time', 'true')]
    )

    # 2. 启动 Nav2 导航（不启动 map_server，因为 SLAM 会直接生成 /map）
    nav2_params = os.path.join(
        get_package_share_directory('nav2_bringup'), 'params', 'nav2_params.yaml')
    
    nav2_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(os.path.join(
            get_package_share_directory('nav2_bringup'), 'launch', 'navigation_launch.py')),
        launch_arguments=[
            ('use_sim_time', 'true'),
            ('params_file', nav2_params),
            ('autostart', 'true')
        ]
    )

    # 3. 启动自主探索节点
    explore_node = Node(
        package='explore_lite',
        executable='explore',
        name='explore',
        output='screen',
        parameters=[{
            'use_sim_time': True,
            'robot_base_frame': 'base_footprint',
            'costmap_topic': 'global_costmap/costmap',
            'costmap_updates_topic': 'global_costmap/costmap_updates',
            'visualize': True,
            
            # 【关键修改 1】降低规划频率：从 0.33 改成 0.1，让它每 10 秒才重新找一次目标，给车足够的时间走过去
            'planner_frequency': 0.1, 
            
            # 【关键修改 2】增加超时容忍度：从 30 秒增加到 60 秒，防止车稍微卡一下就认为目标不可达而放弃
            'progress_timeout': 60.0,
            
            'potential_scale': 3.0,
            'orientation_scale': 0.0,
            'gain_scale': 1.0,
            'transform_tolerance': 0.5,
            
            # 【关键修改 3】减小最小边界尺寸：从 0.75 改成 0.1，让它可以探索门缝、桌子底下等狭小的未知区域
            'min_frontier_size': 0.1 
        }]
    )
        # 延迟 5 秒启动探索节点
    delayed_explore = TimerAction(
        period=5.0,
        actions=[explore_node]
    )

    return LaunchDescription([slam_launch, nav2_launch, delayed_explore])

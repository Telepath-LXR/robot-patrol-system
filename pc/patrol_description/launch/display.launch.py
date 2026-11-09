import os
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch_ros.actions import Node

def generate_launch_description():
    # 获取包路径
    pkg_share = get_package_share_directory('patrol_description')
    urdf_path = os.path.join(pkg_share, 'urdf', 'patrol_robot.urdf')
    
    # 读取 URDF 文件内容
    with open(urdf_path, 'r', encoding='utf-8') as f:
        robot_desc = f.read()

    # 1. 启动 robot_state_publisher（发布 TF 和 /robot_description 话题）
    rsp_node = Node(
        package='robot_state_publisher',
        executable='robot_state_publisher',
        parameters=[{'robot_description': robot_desc}],
        output='screen'
    )

    # 2. 启动 joint_state_publisher_gui（提供滑块，用于控制轮子旋转等连续关节）
    # 如果你的系统没装，终端执行：sudo apt install ros-humble-joint-state-publisher-gui
    jsp_node = Node(
        package='joint_state_publisher_gui',
        executable='joint_state_publisher_gui',
        output='screen'
    )

    # 3. 启动 RViz2（使用 -d 参数可选，后面我们可以存一个配置，现在先直接起）
    rviz_node = Node(
        package='rviz2',
        executable='rviz2',
        output='screen'
    )

    return LaunchDescription([
        rsp_node,
        jsp_node,
        rviz_node
    ])

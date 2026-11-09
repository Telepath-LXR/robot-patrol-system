#!/usr/bin/env python3
"""替代 socat: 创建一对互联的虚拟串口 (/tmp/vser_a <-> /tmp/vser_b).

用法: python3 vserial_pair.py
"""
import os
import pty
import select
import sys
import tty


def main():
    master1, slave1 = pty.openpty()
    master2, slave2 = pty.openpty()

    # 设置 raw 模式, 等价 socat 的 raw,echo=0
    tty.setraw(master1)
    tty.setraw(slave1)
    tty.setraw(master2)
    tty.setraw(slave2)

    name1 = os.ttyname(slave1)
    name2 = os.ttyname(slave2)

    # 建符号链接
    for link, target in [('/tmp/vser_a', name1), ('/tmp/vser_b', name2)]:
        try:
            os.unlink(link)
        except FileNotFoundError:
            pass
        os.symlink(target, link)

    print(f'/tmp/vser_a -> {name1}')
    print(f'/tmp/vser_b -> {name2}')
    print('虚拟串口对已就绪, Ctrl+C 退出')
    sys.stdout.flush()

    # 双向转发
    try:
        while True:
            r, _, _ = select.select([master1, master2], [], [])
            if master1 in r:
                data = os.read(master1, 4096)
                if not data:
                    break
                os.write(master2, data)
            if master2 in r:
                data = os.read(master2, 4096)
                if not data:
                    break
                os.write(master1, data)
    except KeyboardInterrupt:
        pass
    finally:
        for link in ['/tmp/vser_a', '/tmp/vser_b']:
            try:
                os.unlink(link)
            except FileNotFoundError:
                pass
        print('\n虚拟串口对已关闭')


if __name__ == '__main__':
    main()

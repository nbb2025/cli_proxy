#!/usr/bin/env python3
import argparse
from src.codex import ctl as codex
from src.claude import ctl as claude
from src.ui import ctl as ui


def _get_ui_status():
    running = ui.is_running()
    pid = ui.get_pid() if running else None
    return {
        "service": "ui",
        "running": running,
        "pid": pid,
        "port": getattr(ui, "DEFAULT_PORT", 3300),
        "active_config": None,
    }


SERVICE_STATUS_DEFINITIONS = [
    {
        "label": "Claude 代理",
        "status_fn": claude.status,
        "show_config": True,
        "default_port": getattr(claude, "DEFAULT_PORT", 3210),
    },
    {
        "label": "Codex 代理",
        "status_fn": codex.status,
        "show_config": True,
        "default_port": getattr(codex, "DEFAULT_PORT", 3211),
    },
    {
        "label": "UI 服务",
        "status_fn": _get_ui_status,
        "show_config": False,
        "default_port": getattr(ui, "DEFAULT_PORT", 3300),
    },
]

SERVICE_TITLE_MAP = {
    "codex": "Codex",
    "claude": "Claude",
}


def _execute_service_actions(action_name, actions):
    errors = []
    for label, func in actions:
        try:
            result = func()
            if result is False:
                errors.append(f"{label}{action_name}失败")
        except Exception as exc:
            errors.append(f"{label}{action_name}异常: {exc}")
    return errors


def _print_config_list(service_label, configs, active):
    if not configs:
        print(f"{service_label}: 没有可用配置")
        return

    print(f"{service_label} 可用配置:")
    for name in configs:
        if name == active:
            print(f"  * {name} (激活)")
        else:
            print(f"    {name}")

def print_status():
    """显示所有服务的运行状态"""
    print("=== 本地代理 服务运行状态 ===\n")
    for service in SERVICE_STATUS_DEFINITIONS:
        status_data = service["status_fn"]() or {}
        port = status_data.get("port") or service.get("default_port")
        running = status_data.get("running", False)
        pid = status_data.get("pid")

        print(f"{service['label']}:")
        if port:
            print(f"  端口: {port}")

        status_text = "运行中" if running else "已停止"
        pid_text = f" (PID: {pid})" if pid else ""
        print(f"  状态: {status_text}{pid_text}")

        if service.get("show_config"):
            active_config = status_data.get("active_config")
            if active_config:
                print(f"  配置: 激活配置: {active_config}")
            else:
                print("  配置: 无可用配置")
        print()

def main():
    """主函数 - 处理命令行参数"""
    parser = argparse.ArgumentParser(
        description='CLI Proxy - 本地AI代理服务控制工具',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""使用示例:
  clp start                     启动所有服务
  clp stop                      停止所有服务
  clp status                    查看所有服务状态
  clp list claude               列出Claude的所有配置
  clp active claude prod        激活Claude的prod配置""",
        prog='clp'
    )
    common_formatter = parser.formatter_class
    subparsers = parser.add_subparsers(
        dest='command', 
        title='可用命令',
        description='使用 clp <命令> --help 查看具体命令的详细帮助',
        help='命令说明'
    )
    
    # start 命令
    start = subparsers.add_parser(
        'start', 
        help='启动所有代理服务',
        description='启动codex、claude和ui三个服务',
        formatter_class=common_formatter,
        epilog="""示例:
  clp start                     启动所有服务(codex:3211, claude:3210, ui:3300)"""
    )
    
    # stop 命令
    stop = subparsers.add_parser(
        'stop', 
        help='停止所有代理服务',
        description='停止codex、claude和ui三个服务'
    )
    
    # restart 命令
    restart = subparsers.add_parser(
        'restart', 
        help='重启所有代理服务',
        description='重启codex、claude和ui三个服务',
        formatter_class=common_formatter,
        epilog="""示例:
  clp restart                   重启所有服务"""
    )
    
    # active 命令
    active_parser = subparsers.add_parser(
        'active', 
        help='激活指定配置',
        description='设置要使用的配置文件',
        formatter_class=common_formatter,
        epilog="""示例:
  clp active claude prod        激活Claude的prod配置
  clp active codex dev          激活Codex的dev配置"""
    )
    active_parser.add_argument('service', choices=['codex', 'claude'], 
                              help='服务类型', metavar='{codex,claude}')
    active_parser.add_argument('config_name', help='要激活的配置名称')
    
    # list 命令
    lists = subparsers.add_parser(
        'list', 
        help='列出所有配置',
        description='显示指定服务的所有可用配置'
    )
    lists.add_argument('service', choices=['codex', 'claude'], 
                      help='服务类型', metavar='{codex,claude}')
    
    # status 命令
    status_parser = subparsers.add_parser(
        'status', 
        help='显示服务状态',
        description='显示所有代理服务的运行状态、PID和激活配置信息'
    )
    
    # ui 命令
    ui_parser = subparsers.add_parser(
        'ui', 
        help='启动Web UI界面',
        description='启动Web UI界面来可视化代理状态',
        formatter_class=common_formatter,
        epilog="""示例:
  clp ui                        启动UI界面(默认端口3300)"""
    )

    # 解析参数
    args = parser.parse_args()

    if args.command == 'start':
        print("正在启动所有服务...")
        errors = _execute_service_actions(
            ' 启动',
            [
                ("Claude 服务", claude.start),
                ("Codex 服务", codex.start),
                ("UI 服务", ui.start),
            ],
        )
        if errors:
            for message in errors:
                print(message)
        else:
            print("启动完成!")
        print_status()
    elif args.command == 'stop':
        errors = _execute_service_actions(
            ' 停止',
            [
                ("Claude 服务", claude.stop),
                ("Codex 服务", codex.stop),
                ("UI 服务", ui.stop),
            ],
        )
        for message in errors:
            print(message)
    elif args.command == 'restart':
        errors = _execute_service_actions(
            ' 重启',
            [
                ("Claude 服务", claude.restart),
                ("Codex 服务", codex.restart),
                ("UI 服务", ui.restart),
            ],
        )
        for message in errors:
            print(message)
    elif args.command == 'active':
        service_key = args.service
        config_name = args.config_name
        module = codex if service_key == 'codex' else claude
        service_label = SERVICE_TITLE_MAP[service_key]
        try:
            switched = module.set_active_config(config_name)
        except Exception as exc:
            print(f"{service_label}配置切换失败: {exc}")
        else:
            if switched:
                print(f"{service_label}配置已切换到: {config_name}")
            else:
                print(f"配置 {config_name} 不存在")
    elif args.command == 'list':
        service_key = args.service
        module = codex if service_key == 'codex' else claude
        service_label = SERVICE_TITLE_MAP[service_key]
        try:
            configs, active_config = module.list_configs()
        except Exception as exc:
            print(f"{service_label}配置读取失败: {exc}")
        else:
            _print_config_list(service_label, configs, active_config)
    elif args.command == 'status':
        print_status()
    elif args.command == 'ui':
        import webbrowser
        webbrowser.open("http://localhost:3300")
    else:
        parser.print_help()

if __name__ == '__main__':
    main()

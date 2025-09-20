#!/usr/bin/env python3
import os
import sys
import signal
import subprocess
import psutil

def is_process_running(pid):
    """跨平台检查进程是否运行"""
    if pid is None:
        return False
    
    try:
        # 使用psutil库进行跨平台进程检测
        process = psutil.Process(pid)
        return process.is_running()
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return False

def kill_process(pid, force=False):
    """跨平台杀死进程及其子进程"""
    if not is_process_running(pid):
        return True
    
    try:
        process = psutil.Process(pid)
        
        # 获取所有子进程
        children = process.children(recursive=True)
        
        # 先终止子进程
        for child in children:
            try:
                if force:
                    child.kill()
                else:
                    child.terminate()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        
        # 再终止主进程
        if force:
            process.kill()
        else:
            process.terminate()
        
        # 等待所有进程结束
        gone, still_alive = psutil.wait_procs(children + [process], timeout=5)
        
        # 强制杀死仍然存活的进程
        for p in still_alive:
            try:
                p.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        
        return True
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return True  # 进程已经不存在

def create_detached_process(cmd, log_file):
    """跨平台创建分离进程"""
    try:
        if sys.platform == "win32":
            # Windows下的分离进程 - 隐藏窗口
            proc = subprocess.Popen(
                cmd,
                stdout=log_file,
                stderr=log_file,
                stdin=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
            )
        else:
            # Unix/Linux下的分离进程
            proc = subprocess.Popen(
                cmd,
                stdout=log_file,
                stderr=log_file,
                stdin=subprocess.DEVNULL,
                start_new_session=True
            )
        
        return proc
    except Exception as e:
        raise RuntimeError(f"创建分离进程失败: {e}")
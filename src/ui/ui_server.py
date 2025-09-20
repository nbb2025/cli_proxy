import json
import webbrowser
import time
from pathlib import Path
from typing import Any, Dict
from flask import Flask, jsonify, send_file, request
import os

from src.utils.usage_parser import (
    METRIC_KEYS,
    empty_metrics,
    format_usage_value,
    merge_usage_metrics,
    normalize_usage_record,
)

# 数据目录 - 使用绝对路径
DATA_DIR = Path.home() / '.clp/data'
DATA_DIR.mkdir(parents=True, exist_ok=True)
STATIC_DIR = Path(__file__).resolve().parent / 'static'

LOG_FILE = DATA_DIR / 'proxy_requests.jsonl'
OLD_LOG_FILE = DATA_DIR / 'traffic_statistics.jsonl'
HISTORY_FILE = DATA_DIR / 'history_usage.json'

if OLD_LOG_FILE.exists() and not LOG_FILE.exists():
    try:
        OLD_LOG_FILE.rename(LOG_FILE)
    except OSError:
        pass

app = Flask(__name__, static_folder=str(STATIC_DIR), static_url_path='/static')


def _safe_json_load(line: str) -> Dict[str, Any]:
    try:
        return json.loads(line)
    except json.JSONDecodeError:
        return {}


def _config_signature(config_entry: Dict[str, Any]) -> tuple:
    """Create a comparable signature for a config entry to help detect renames."""
    if not isinstance(config_entry, dict):
        return tuple()
    return (
        config_entry.get('base_url'),
        config_entry.get('auth_token'),
        config_entry.get('api_key'),
    )


def _detect_config_renames(old_configs: Dict[str, Any], new_configs: Dict[str, Any]) -> Dict[str, str]:
    """Return mapping of {old_name: new_name} for configs that only changed key names."""
    rename_map: Dict[str, str] = {}
    if not isinstance(old_configs, dict) or not isinstance(new_configs, dict):
        return rename_map

    old_signatures: Dict[tuple, list[str]] = {}
    for name, cfg in old_configs.items():
        sig = _config_signature(cfg)
        old_signatures.setdefault(sig, []).append(name)

    new_signatures: Dict[tuple, list[str]] = {}
    for name, cfg in new_configs.items():
        sig = _config_signature(cfg)
        new_signatures.setdefault(sig, []).append(name)

    for signature, old_names in old_signatures.items():
        new_names = new_signatures.get(signature)
        if not new_names:
            continue
        if set(old_names) == set(new_names):
            continue
        if len(old_names) == len(new_names) == 1:
            old_name = old_names[0]
            new_name = new_names[0]
            if old_name != new_name:
                rename_map[old_name] = new_name

    return rename_map


def _rename_history_channels(service: str, rename_map: Dict[str, str]) -> None:
    if not rename_map:
        return
    history_usage = load_history_usage()
    service_bucket = history_usage.get(service)
    if not service_bucket:
        return

    changed = False
    for old_name, new_name in rename_map.items():
        if old_name == new_name:
            continue
        if old_name not in service_bucket:
            continue

        existing_metrics = service_bucket.pop(old_name)
        target_metrics = service_bucket.get(new_name)
        if target_metrics:
            merge_usage_metrics(target_metrics, existing_metrics)
        else:
            service_bucket[new_name] = existing_metrics
        changed = True

    if changed:
        save_history_usage(history_usage)


def _rename_log_channels(service: str, rename_map: Dict[str, str]) -> None:
    if not rename_map or not LOG_FILE.exists():
        return

    temp_path = LOG_FILE.with_suffix('.tmp')
    try:
        with open(LOG_FILE, 'r', encoding='utf-8') as src, open(temp_path, 'w', encoding='utf-8') as dst:
            for raw_line in src:
                if not raw_line.strip():
                    dst.write(raw_line)
                    continue
                try:
                    record = json.loads(raw_line)
                except json.JSONDecodeError:
                    dst.write(raw_line)
                    continue

                if record.get('service') == service:
                    channel_name = record.get('channel')
                    if channel_name in rename_map:
                        record['channel'] = rename_map[channel_name]
                        raw_line = json.dumps(record, ensure_ascii=False) + '\n'
                dst.write(raw_line)
    except Exception:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)
        raise

    temp_path.replace(LOG_FILE)


def _apply_channel_renames(service: str, rename_map: Dict[str, str]) -> None:
    if not rename_map:
        return
    _rename_history_channels(service, rename_map)
    _rename_log_channels(service, rename_map)


def load_logs() -> list[Dict[str, Any]]:
    logs: list[Dict[str, Any]] = []
    log_path = LOG_FILE if LOG_FILE.exists() else (
        OLD_LOG_FILE if OLD_LOG_FILE.exists() else None
    )
    if log_path is None:
        return logs

    with open(log_path, 'r', encoding='utf-8') as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line:
                continue
            entry = _safe_json_load(line)
            if not entry:
                continue
            service = entry.get('service') or entry.get('usage', {}).get('service') or 'unknown'
            entry['usage'] = normalize_usage_record(service, entry.get('usage'))
            logs.append(entry)
    return logs


def load_history_usage() -> Dict[str, Dict[str, Dict[str, int]]]:
    if not HISTORY_FILE.exists():
        return {}
    try:
        with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}

    history: Dict[str, Dict[str, Dict[str, int]]] = {}
    for service, channels in (data or {}).items():
        if not isinstance(channels, dict):
            continue
        service_bucket: Dict[str, Dict[str, int]] = {}
        for channel, metrics in channels.items():
            normalized = empty_metrics()
            if isinstance(metrics, dict):
                merge_usage_metrics(normalized, metrics)
            service_bucket[channel] = normalized
        history[service] = service_bucket
    return history


def save_history_usage(data: Dict[str, Dict[str, Dict[str, int]]]) -> None:
    serializable = {
        service: {
            channel: {key: int(value) for key, value in metrics.items()}
            for channel, metrics in channels.items()
        }
        for service, channels in data.items()
    }
    with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(serializable, f, ensure_ascii=False, indent=2)


def aggregate_usage_from_logs(logs: list[Dict[str, Any]]) -> Dict[str, Dict[str, Dict[str, int]]]:
    aggregated: Dict[str, Dict[str, Dict[str, int]]] = {}
    for entry in logs:
        usage = entry.get('usage', {})
        metrics = usage.get('metrics', {})
        if not metrics:
            continue
        service = usage.get('service') or entry.get('service') or 'unknown'
        channel = entry.get('channel') or 'unknown'
        service_bucket = aggregated.setdefault(service, {})
        channel_bucket = service_bucket.setdefault(channel, empty_metrics())
        merge_usage_metrics(channel_bucket, metrics)
    return aggregated


def merge_history_usage(base: Dict[str, Dict[str, Dict[str, int]]],
                        addition: Dict[str, Dict[str, Dict[str, int]]]) -> Dict[str, Dict[str, Dict[str, int]]]:
    for service, channels in addition.items():
        service_bucket = base.setdefault(service, {})
        for channel, metrics in channels.items():
            channel_bucket = service_bucket.setdefault(channel, empty_metrics())
            merge_usage_metrics(channel_bucket, metrics)
    return base


def combine_usage_maps(current: Dict[str, Dict[str, Dict[str, int]]],
                       history: Dict[str, Dict[str, Dict[str, int]]]) -> Dict[str, Dict[str, Dict[str, int]]]:
    combined: Dict[str, Dict[str, Dict[str, int]]] = {}
    services = set(current.keys()) | set(history.keys())
    for service in services:
        combined_channels: Dict[str, Dict[str, int]] = {}
        current_channels = current.get(service, {})
        history_channels = history.get(service, {})
        all_channels = set(current_channels.keys()) | set(history_channels.keys())
        for channel in all_channels:
            metrics = empty_metrics()
            if channel in current_channels:
                merge_usage_metrics(metrics, current_channels[channel])
            if channel in history_channels:
                merge_usage_metrics(metrics, history_channels[channel])
            combined_channels[channel] = metrics
        combined[service] = combined_channels
    return combined


def compute_total_metrics(channels_map: Dict[str, Dict[str, int]]) -> Dict[str, int]:
    totals = empty_metrics()
    for metrics in channels_map.values():
        merge_usage_metrics(totals, metrics)
    return totals


def format_metrics(metrics: Dict[str, int]) -> Dict[str, str]:
    return {key: format_usage_value(metrics.get(key, 0)) for key in METRIC_KEYS}


def build_usage_snapshot() -> Dict[str, Any]:
    logs = load_logs()
    current_usage = aggregate_usage_from_logs(logs)
    history_usage = load_history_usage()
    combined_usage = combine_usage_maps(current_usage, history_usage)
    return {
        'logs': logs,
        'current_usage': current_usage,
        'history_usage': history_usage,
        'combined_usage': combined_usage
    }

@app.route('/')
def index():
    """返回主页"""
    index_file = STATIC_DIR / 'index.html'
    return send_file(index_file)

@app.route('/static/<path:filename>')
def static_files(filename):
    """返回静态文件"""
    return send_file(STATIC_DIR / filename)

@app.route('/api/status')
def get_status():
    """获取服务状态"""
    try:
        # 直接获取实时服务状态，不依赖status.json文件
        from src.claude import ctl as claude
        from src.codex import ctl as codex
        from src.config.cached_config_manager import claude_config_manager, codex_config_manager
        
        claude_running = claude.is_running()
        claude_pid = claude.get_pid() if claude_running else None
        claude_config = claude_config_manager.active_config
        
        codex_running = codex.is_running()
        codex_pid = codex.get_pid() if codex_running else None
        codex_config = codex_config_manager.active_config
        
        # 计算配置数量
        claude_configs = len(claude_config_manager.configs)
        codex_configs = len(codex_config_manager.configs)
        total_configs = claude_configs + codex_configs
        
        usage_snapshot = build_usage_snapshot()
        logs = usage_snapshot['logs']
        request_count = len(logs)
        combined_usage = usage_snapshot['combined_usage']

        service_usage_totals: Dict[str, Dict[str, int]] = {}
        for service_name, channels in combined_usage.items():
            service_usage_totals[service_name] = compute_total_metrics(channels)

        for expected_service in ('claude', 'codex'):
            service_usage_totals.setdefault(expected_service, empty_metrics())

        overall_totals = empty_metrics()
        for totals in service_usage_totals.values():
            merge_usage_metrics(overall_totals, totals)

        usage_summary = {
            'totals': overall_totals,
            'formatted_totals': format_metrics(overall_totals),
            'per_service': {
                service: {
                    'metrics': totals,
                    'formatted': format_metrics(totals)
                }
                for service, totals in service_usage_totals.items()
            }
        }
        
        # 计算过滤规则数量
        filter_file = Path.home() / '.clp' / 'filter.json'
        filter_count = 0
        if filter_file.exists():
            try:
                with open(filter_file, 'r', encoding='utf-8') as f:
                    filter_data = json.load(f)
                    if isinstance(filter_data, list):
                        filter_count = len(filter_data)
                    elif isinstance(filter_data, dict):
                        filter_count = 1
            except (json.JSONDecodeError, IOError):
                filter_count = 0
        
        data = {
            'services': {
                'claude': {
                    'running': claude_running,
                    'pid': claude_pid,
                    'config': claude_config
                },
                'codex': {
                    'running': codex_running,
                    'pid': codex_pid,
                    'config': codex_config
                }
            },
            'request_count': request_count,
            'config_count': total_configs,
            'filter_count': filter_count,
            'last_updated': time.strftime('%Y-%m-%dT%H:%M:%S'),
            'usage_summary': usage_summary
        }
        
        return jsonify(data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/config/<service>', methods=['GET'])
def get_config(service):
    """获取配置文件内容"""
    try:
        if service not in ['claude', 'codex']:
            return jsonify({'error': 'Invalid service name'}), 400
        
        config_file = Path.home() / '.clp' / f'{service}.json'
        config_file.parent.mkdir(parents=True, exist_ok=True)

        if not config_file.exists():
            with open(config_file, 'w', encoding='utf-8') as f:
                json.dump({}, f, ensure_ascii=False, indent=2)

        content = config_file.read_text(encoding='utf-8')
        if not content.strip():
            with open(config_file, 'w', encoding='utf-8') as f:
                json.dump({}, f, ensure_ascii=False, indent=2)
            content = config_file.read_text(encoding='utf-8')

        return jsonify({'content': content})
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/config/<service>', methods=['POST'])
def save_config(service):
    """保存配置文件内容"""
    try:
        if service not in ['claude', 'codex']:
            return jsonify({'error': 'Invalid service name'}), 400
        
        data = request.get_json()
        content = data.get('content', '')

        if not content:
            return jsonify({'error': 'Content cannot be empty'}), 400

        # 验证JSON格式
        try:
            new_configs = json.loads(content)
        except json.JSONDecodeError as e:
            return jsonify({'error': f'Invalid JSON format: {str(e)}'}), 400

        config_file = Path.home() / '.clp' / f'{service}.json'
        old_content = None
        old_configs: Dict[str, Any] = {}

        if config_file.exists():
            with open(config_file, 'r', encoding='utf-8') as f:
                old_content = f.read()
            try:
                old_configs = json.loads(old_content)
            except json.JSONDecodeError:
                old_configs = {}

        rename_map = _detect_config_renames(old_configs, new_configs)

        try:
            # 直接写入新内容
            with open(config_file, 'w', encoding='utf-8') as f:
                f.write(content)

            _apply_channel_renames(service, rename_map)
        except Exception as exc:
            # 恢复旧配置，避免部分成功
            if old_content is not None:
                with open(config_file, 'w', encoding='utf-8') as f:
                    f.write(old_content)
            else:
                config_file.unlink(missing_ok=True)
            return jsonify({'error': f'配置保存失败: {exc}'}), 500

        return jsonify({'success': True, 'message': f'{service}配置保存成功'})
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/filter', methods=['GET'])
def get_filter():
    """获取过滤规则文件内容"""
    try:
        filter_file = Path.home() / '.clp' / 'filter.json'
        
        if not filter_file.exists():
            # 创建默认的过滤规则文件
            default_content = '[\n  {\n    "source": "example_text",\n    "target": "replacement_text",\n    "op": "replace"\n  }\n]'
            return jsonify({'content': default_content})
        
        with open(filter_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        return jsonify({'content': content})
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/filter', methods=['POST'])
def save_filter():
    """保存过滤规则文件内容"""
    try:
        data = request.get_json()
        content = data.get('content', '')
        
        if not content:
            return jsonify({'error': 'Content cannot be empty'}), 400
        
        # 验证JSON格式
        try:
            filter_data = json.loads(content)
            # 验证过滤规则格式
            if isinstance(filter_data, list):
                for rule in filter_data:
                    if not isinstance(rule, dict):
                        return jsonify({'error': 'Each filter rule must be an object'}), 400
                    if 'source' not in rule or 'op' not in rule:
                        return jsonify({'error': 'Each rule must have "source" and "op" fields'}), 400
                    if rule['op'] not in ['replace', 'remove']:
                        return jsonify({'error': 'op must be "replace" or "remove"'}), 400
                    if rule['op'] == 'replace' and 'target' not in rule:
                        return jsonify({'error': 'replace operation requires "target" field'}), 400
            elif isinstance(filter_data, dict):
                if 'source' not in filter_data or 'op' not in filter_data:
                    return jsonify({'error': 'Rule must have "source" and "op" fields'}), 400
                if filter_data['op'] not in ['replace', 'remove']:
                    return jsonify({'error': 'op must be "replace" or "remove"'}), 400
                if filter_data['op'] == 'replace' and 'target' not in filter_data:
                    return jsonify({'error': 'replace operation requires "target" field'}), 400
            else:
                return jsonify({'error': 'Filter data must be an object or array of objects'}), 400
                
        except json.JSONDecodeError as e:
            return jsonify({'error': f'Invalid JSON format: {str(e)}'}), 400
        
        filter_file = Path.home() / '.clp' / 'filter.json'
        
        # 直接写入新内容，不进行备份
        with open(filter_file, 'w', encoding='utf-8') as f:
            f.write(content)
        
        return jsonify({'success': True, 'message': '过滤规则保存成功'})
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/logs')
def get_logs():
    """获取请求日志"""
    try:
        logs = load_logs()
        return jsonify(logs[-10:][::-1])
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/logs/all')
def get_all_logs():
    """获取所有请求日志"""
    try:
        logs = load_logs()
        return jsonify(logs[::-1])
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/logs', methods=['DELETE'])
def clear_logs():
    """清空所有日志"""
    try:
        logs = load_logs()
        if logs:
            aggregated = aggregate_usage_from_logs(logs)
            if aggregated:
                history_usage = load_history_usage()
                merged = merge_history_usage(history_usage, aggregated)
                save_history_usage(merged)

        log_path = LOG_FILE if LOG_FILE.exists() else (
            OLD_LOG_FILE if OLD_LOG_FILE.exists() else LOG_FILE
        )
        log_path.write_text('', encoding='utf-8')
        if log_path != LOG_FILE:
            LOG_FILE.touch(exist_ok=True)
        
        return jsonify({'success': True, 'message': '日志已清空'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/usage/details')
def get_usage_details():
    """返回合并后的usage明细"""
    try:
        snapshot = build_usage_snapshot()
        combined_usage = snapshot['combined_usage']

        services_payload: Dict[str, Any] = {}
        for service, channels in combined_usage.items():
            overall_metrics = compute_total_metrics(channels)
            services_payload[service] = {
                'overall': {
                    'metrics': overall_metrics,
                    'formatted': format_metrics(overall_metrics)
                },
                'channels': {
                    channel: {
                        'metrics': metrics,
                        'formatted': format_metrics(metrics)
                    }
                    for channel, metrics in channels.items()
                }
            }

        totals_metrics = empty_metrics()
        for service_data in services_payload.values():
            merge_usage_metrics(totals_metrics, service_data['overall']['metrics'])

        response = {
            'totals': {
                'metrics': totals_metrics,
                'formatted': format_metrics(totals_metrics)
            },
            'services': services_payload
        }
        return jsonify(response)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/usage/clear', methods=['DELETE'])
def clear_usage():
    """清空Token使用记录"""
    try:
        # 1. 先清空日志（复用现有功能）
        logs = load_logs()
        if logs:
            aggregated = aggregate_usage_from_logs(logs)
            if aggregated:
                history_usage = load_history_usage()
                merged = merge_history_usage(history_usage, aggregated)
                save_history_usage(merged)

        log_path = LOG_FILE if LOG_FILE.exists() else (
            OLD_LOG_FILE if OLD_LOG_FILE.exists() else LOG_FILE
        )
        log_path.write_text('', encoding='utf-8')
        if log_path != LOG_FILE:
            LOG_FILE.touch(exist_ok=True)

        # 2. 清空 history_usage.json 中的所有数值
        history_usage = load_history_usage()
        for service in history_usage:
            for channel in history_usage[service]:
                for key in history_usage[service][channel]:
                    history_usage[service][channel][key] = 0
        save_history_usage(history_usage)

        return jsonify({'success': True, 'message': 'Token使用记录已清空'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/switch-config', methods=['POST'])
def switch_config():
    """切换激活配置"""
    try:
        data = request.get_json()
        service = data.get('service')
        config = data.get('config')
        
        if not service or not config:
            return jsonify({'error': 'Missing service or config parameter'}), 400
        
        if service not in ['claude', 'codex']:
            return jsonify({'error': 'Invalid service name'}), 400
        
        # 导入对应的配置管理器
        if service == 'claude':
            from src.config.cached_config_manager import claude_config_manager as config_manager
        else:
            from src.config.cached_config_manager import codex_config_manager as config_manager
        
        # 切换配置
        if config_manager.set_active_config(config):
            # 验证配置确实已切换
            actual_config = config_manager.active_config
            if actual_config == config:
                return jsonify({
                    'success': True, 
                    'message': f'{service}配置已切换到: {config}',
                    'active_config': actual_config
                })
            else:
                return jsonify({
                    'success': False, 
                    'message': f'配置切换验证失败，当前配置: {actual_config}'
                })
        else:
            return jsonify({'success': False, 'message': f'配置{config}不存在'})
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500

def start_ui_server(port=3300):
    """启动UI服务器并打开浏览器"""
    print(f"启动Web UI服务器在端口 {port}")

    # 启动Flask应用
    app.run(host='0.0.0.0', port=port, debug=False)

if __name__ == '__main__':
    start_ui_server()

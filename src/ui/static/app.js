// Vue 3 + Element Plus CLI Proxy Monitor Application
const { createApp, ref, reactive, onMounted, nextTick } = Vue;
const { ElMessage, ElMessageBox } = ElementPlus;

const app = createApp({
    setup() {
        // 响应式数据
        const loading = ref(false);
        const logsLoading = ref(false);
        const allLogsLoading = ref(false);
        const configSaving = ref(false);
        const filterSaving = ref(false);
        const lastUpdate = ref('加载中...');
        
        // 服务状态数据
        const services = reactive({
            claude: {
                running: false,
                pid: null,
                config: ''
            },
            codex: {
                running: false,
                pid: null,
                config: ''
            }
        });
        
        // 统计数据
        const stats = reactive({
            requestCount: 0,
            configCount: 0,
            filterCount: 0
        });
        
        // 日志数据
        const logs = ref([]);
        const allLogs = ref([]);
        
        // 配置选项
        const claudeConfigs = ref([]);
        const codexConfigs = ref([]);
        
        // 抽屉状态
        const configDrawerVisible = ref(false);
        const filterDrawerVisible = ref(false);
        const logDetailVisible = ref(false);
        const allLogsVisible = ref(false);
        const activeConfigTab = ref('claude');
        const activeLogTab = ref('basic'); // 日志详情Tab状态
        
        // 配置内容
        const configContents = reactive({
            claude: '',
            codex: ''
        });
        const filterContent = ref('');
        const filterRules = ref([]);  // 过滤规则数组
        const selectedLog = ref(null);
        const decodedRequestBody = ref(''); // 解码后的请求体（转换后）
        const decodedOriginalRequestBody = ref(''); // 解码后的原始请求体
        const decodedResponseContent = ref(''); // 解码后的响应内容

        const metricKeys = ['input', 'cached_create', 'cached_read', 'output', 'reasoning', 'total'];
        const createEmptyMetrics = () => ({
            input: 0,
            cached_create: 0,
            cached_read: 0,
            output: 0,
            reasoning: 0,
            total: 0
        });
        const createEmptyFormatted = () => {
            const formatted = {};
            metricKeys.forEach(key => {
                formatted[key] = '0';
            });
            return formatted;
        };

        const usageSummary = reactive({
            totals: createEmptyMetrics(),
            formattedTotals: createEmptyFormatted(),
            perService: {}
        });
        const usageDrawerVisible = ref(false);
        const usageDetailsLoading = ref(false);
        const usageDetails = reactive({
            totals: {
                metrics: createEmptyMetrics(),
                formatted: createEmptyFormatted()
            },
            services: {}
        });
        const usageMetricLabels = {
            input: '输入',
            cached_create: '缓存创建',
            cached_read: '缓存读取',
            output: '输出',
            reasoning: '思考',
            total: '总计'
        };
        
        const normalizeUsageBlock = (block) => {
            const isMetricsMap = block && typeof block === 'object' && !Array.isArray(block) && metricKeys.some(key => key in block);
            const metricsSource = isMetricsMap ? block : (block?.metrics || {});
            const formattedSource = block?.formatted || {};
            const displayMetricsSource = block?.displayMetrics || metricsSource;
            const displayFormattedSource = block?.displayFormatted || formattedSource;

            return {
                metrics: Object.assign(createEmptyMetrics(), metricsSource || {}),
                formatted: Object.assign(createEmptyFormatted(), formattedSource || {}),
                displayMetrics: Object.assign(createEmptyMetrics(), displayMetricsSource || {}),
                displayFormatted: Object.assign(createEmptyFormatted(), displayFormattedSource || {}),
            };
        };

        const resetUsageSummary = () => {
            usageSummary.totals = createEmptyMetrics();
            usageSummary.formattedTotals = createEmptyFormatted();
            usageSummary.perService = {};
        };

        const resetUsageDetails = () => {
            usageDetails.totals = normalizeUsageBlock({});
            usageDetails.services = {};
        };

        const formatUsageValue = (value) => {
            const num = Number(value || 0);
            if (!Number.isFinite(num)) {
                return '-';
            }
            const intVal = Math.trunc(num);
            if (intVal >= 1_000_000) {
                const short = Math.floor(intVal / 100_000) / 10;
                return `${intVal} (${short.toFixed(1)}m)`;
            }
            if (intVal >= 1_000) {
                const short = Math.floor(intVal / 100) / 10;
                return `${intVal} (${short.toFixed(1)}k)`;
            }
            return `${intVal}`;
        };

        const getNumeric = (value) => {
            const num = Number(value || 0);
            return Number.isFinite(num) ? num : 0;
        };

        const updateFormattedFromMetrics = (block) => {
            if (!block) {
                return block;
            }
            if (!block.metrics) {
                block.metrics = createEmptyMetrics();
            }
            if (!block.displayMetrics) {
                block.displayMetrics = Object.assign(createEmptyMetrics(), block.metrics);
            }
            if (!block.displayFormatted) {
                block.displayFormatted = createEmptyFormatted();
            }
            metricKeys.forEach(key => {
                block.displayFormatted[key] = formatUsageValue(getNumeric(block.displayMetrics?.[key]));
            });
            block.formatted = block.displayFormatted;
            return block;
        };

        const adjustUsageBlockForService = (service, block) => {
            const normalized = normalizeUsageBlock(block);
            if (!normalized.metrics) {
                return normalized;
            }
            if (service === 'codex') {
                const cachedRead = getNumeric(normalized.metrics.cached_read);
                const adjustedInput = Math.max(0, getNumeric(normalized.metrics.input) - cachedRead);
                const adjustedTotal = Math.max(0, getNumeric(normalized.metrics.total) - cachedRead);
                normalized.displayMetrics.input = adjustedInput;
                normalized.displayMetrics.total = adjustedTotal;
                normalized.displayMetrics.cached_read = getNumeric(normalized.metrics.cached_read);
            } else {
                normalized.displayMetrics = Object.assign(createEmptyMetrics(), normalized.metrics);
            }
            return updateFormattedFromMetrics(normalized);
        };

        const mergeMetricsInto = (target, sourceMetrics) => {
            if (!sourceMetrics) {
                return;
            }
            metricKeys.forEach(key => {
                target[key] = getNumeric(target[key]) + getNumeric(sourceMetrics?.[key]);
            });
        };

        const formatUsageSummary = (usage, serviceOverride = null) => {
            if (!usage || !usage.metrics) {
                return '-';
            }
            const metrics = usage.metrics;
            const service = serviceOverride || usage.service || '';
            const cachedRead = getNumeric(metrics.cached_read);
            const displayInput = service === 'codex'
                ? Math.max(0, getNumeric(metrics.input) - cachedRead)
                : getNumeric(metrics.input);
            const displayTotal = service === 'codex'
                ? Math.max(0, getNumeric(metrics.total) - cachedRead)
                : getNumeric(metrics.total);
            const displayOutput = getNumeric(metrics.output);

            return [
                `IN ${formatUsageValue(displayInput)}`,
                `OUT ${formatUsageValue(displayOutput)}`,
                `Total ${formatUsageValue(displayTotal)}`
            ].join('\n');
        };

        const getUsageFormattedValue = (block, key) => {
            if (!block) return '-';
            const formattedBlock = block.displayFormatted || block.formatted;
            if (formattedBlock && formattedBlock[key]) {
                return formattedBlock[key];
            }
            const metricsSource = block.displayMetrics || block.metrics;
            if (metricsSource) {
                return formatUsageValue(metricsSource[key]);
            }
            return '-';
        };

        const formatChannelName = (name) => {
            if (!name) return '未知';
            return name === 'unknown' ? '未标记' : name;
        };

        // 格式化服务和渠道组合显示（换行形式）
        const formatServiceWithChannel = (service, channel) => {
            const serviceName = service || '-';
            if (!channel || channel === 'unknown') {
                return serviceName;
            }
            return `${serviceName}\n[${channel}]`;
        };

        // 格式化方法和URL的组合
        const formatMethodWithURL = (method, url) => {
            const methodName = method || 'GET';
            const urlPath = url || '-';
            return `[${methodName}] ${urlPath}`;
        };

        const loadUsageDetails = async () => {
            usageDetailsLoading.value = true;
            try {
                const data = await fetchWithErrorHandling('/api/usage/details');
                const services = {};
                const serviceEntries = Object.entries(data.services || {});
                serviceEntries.forEach(([service, payload]) => {
                    const overallBlock = adjustUsageBlockForService(service, payload?.overall || {});
                    const channels = {};
                    Object.entries(payload?.channels || {}).forEach(([channel, channelPayload]) => {
                        if (!channel || channel === 'unknown') {
                            return;
                        }
                        channels[channel] = adjustUsageBlockForService(service, channelPayload || {});
                    });
                    services[service] = {
                        overall: overallBlock,
                        channels
                    };
                });
                usageDetails.services = services;

                if (serviceEntries.length === 0) {
                    usageDetails.totals = adjustUsageBlockForService('codex', data.totals || {});
                } else {
                    const totalMetrics = createEmptyMetrics();
                    serviceEntries.forEach(([service]) => {
                        mergeMetricsInto(totalMetrics, services[service]?.overall?.displayMetrics || services[service]?.overall?.metrics);
                    });
                    usageDetails.totals = updateFormattedFromMetrics({
                        metrics: Object.assign(createEmptyMetrics(), totalMetrics),
                        displayMetrics: Object.assign(createEmptyMetrics(), totalMetrics),
                        formatted: createEmptyFormatted()
                    });
                }
            } catch (error) {
                resetUsageDetails();
                ElMessage.error('获取Usage详情失败: ' + error.message);
            } finally {
                usageDetailsLoading.value = false;
            }
        };

        const openUsageDrawer = async () => {
            usageDrawerVisible.value = true;
            await loadUsageDetails();
        };

        const closeUsageDrawer = () => {
            usageDrawerVisible.value = false;
        };

        // 清空Token使用数据
        const clearUsageData = async () => {
            try {
                await ElMessageBox.confirm(
                    '确定要清空所有Token使用记录吗？此操作将清空所有日志并重置Token统计数据，不可撤销。',
                    '确认清空Token',
                    {
                        confirmButtonText: '确定',
                        cancelButtonText: '取消',
                        type: 'warning',
                    }
                );

                const result = await fetchWithErrorHandling('/api/usage/clear', {
                    method: 'DELETE'
                });

                if (result.success) {
                    ElMessage.success('Token使用记录已清空');
                    // 刷新页面数据
                    window.location.reload();
                } else {
                    ElMessage.error('清空Token失败: ' + (result.error || '未知错误'));
                }
            } catch (error) {
                if (error !== 'cancel') {
                    ElMessage.error('清空Token失败: ' + error.message);
                }
            }
        };

        // API 请求方法
        const fetchWithErrorHandling = async (url, options = {}) => {
            try {
                const response = await fetch(url, options);
                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}: ${response.statusText}`);
                }
                return await response.json();
            } catch (error) {
                console.error(`API请求失败 ${url}:`, error);
                throw error;
            }
        };
        
        // 加载状态数据
        const loadStatus = async () => {
            try {
                const data = await fetchWithErrorHandling('/api/status');
                updateServiceStatus(data);
                updateStats(data);
            } catch (error) {
                ElMessage.error('获取状态失败: ' + error.message);
            }
        };
        
        // 更新服务状态
        const updateServiceStatus = (data) => {
            if (data.services?.claude) {
                Object.assign(services.claude, data.services.claude);
            }
            if (data.services?.codex) {
                Object.assign(services.codex, data.services.codex);
            }
        };
        
        // 更新统计信息
        const updateStats = (data) => {
            stats.requestCount = data.request_count || 0;
            stats.configCount = data.config_count || 0;
            stats.filterCount = data.filter_count || 0;

            const summary = data.usage_summary || null;
            if (summary) {
                const perService = {};
                const totalMetrics = createEmptyMetrics();
                Object.entries(summary.per_service || {}).forEach(([service, payload]) => {
                    if (!service || service === 'unknown') {
                        return;
                    }
                    const adjusted = adjustUsageBlockForService(service, payload || {});
                    perService[service] = adjusted;
                    mergeMetricsInto(totalMetrics, adjusted.displayMetrics || adjusted.metrics);
                });

                ['claude', 'codex'].forEach(service => {
                    if (!perService[service]) {
                        perService[service] = adjustUsageBlockForService(service, {});
                    }
                });

                usageSummary.perService = perService;

                let totalsBlock;
                if (Object.keys(perService).length === 0 && summary.totals) {
                    totalsBlock = adjustUsageBlockForService('codex', summary.totals || {});
                } else {
                    totalsBlock = updateFormattedFromMetrics({
                        metrics: Object.assign(createEmptyMetrics(), totalMetrics),
                        displayMetrics: Object.assign(createEmptyMetrics(), totalMetrics),
                        formatted: createEmptyFormatted()
                    });
                }
                usageSummary.totals = Object.assign(createEmptyMetrics(), totalsBlock.displayMetrics || totalsBlock.metrics);
                usageSummary.formattedTotals = Object.assign(createEmptyFormatted(), totalsBlock.displayFormatted || totalsBlock.formatted);
            } else {
                resetUsageSummary();
            }
        };
        
        // 加载日志
        const loadLogs = async () => {
            logsLoading.value = true;
            try {
                const data = await fetchWithErrorHandling('/api/logs');
                logs.value = Array.isArray(data) ? data : [];
            } catch (error) {
                ElMessage.error('获取日志失败: ' + error.message);
                logs.value = [];
            } finally {
                logsLoading.value = false;
            }
        };
        
        // 加载配置选项
        const loadConfigOptions = async () => {
            try {
                // 加载Claude配置选项
                const claudeData = await fetchWithErrorHandling('/api/config/claude');
                if (claudeData.content) {
                    const configs = JSON.parse(claudeData.content);
                    claudeConfigs.value = Object.keys(configs).filter(key => 
                        key && key !== 'undefined' && configs[key] !== undefined
                    );
                }
                
                // 加载Codex配置选项
                const codexData = await fetchWithErrorHandling('/api/config/codex');
                if (codexData.content) {
                    const configs = JSON.parse(codexData.content);
                    codexConfigs.value = Object.keys(configs).filter(key => 
                        key && key !== 'undefined' && configs[key] !== undefined
                    );
                }
            } catch (error) {
                console.error('加载配置选项失败:', error);
            }
        };
        
        // 主数据加载方法
        const loadData = async () => {
            loading.value = true;
            try {
                await loadConfigOptions();
                await Promise.all([
                    loadStatus(),
                    loadLogs()
                ]);
                updateLastUpdateTime();
            } catch (error) {
                console.error('加载数据失败:', error);
                ElMessage.error('数据加载失败');
            } finally {
                loading.value = false;
            }
        };
        
        // 刷新页面
        const refreshData = () => {
            window.location.reload();
        };
        
        // 更新最后更新时间
        const updateLastUpdateTime = () => {
            const now = new Date();
            const timeString = now.toLocaleTimeString('zh-CN', { hour12: false });
            lastUpdate.value = `最后更新: ${timeString}`;
        };
        
        // 配置切换
        const switchConfig = async (serviceName, configName) => {
            if (!configName) return;
            
            try {
                const result = await fetchWithErrorHandling('/api/switch-config', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        service: serviceName,
                        config: configName
                    })
                });
                
                if (result.success) {
                    ElMessage.success(`${serviceName}配置已切换到: ${configName}`);
                    // 更新本地状态，避免不必要的重新加载
                    services[serviceName].config = configName;
                    updateLastUpdateTime();
                } else {
                    ElMessage.error(result.message || '配置切换失败');
                    // 失败时恢复原始配置选择
                    await loadStatus();
                }
            } catch (error) {
                ElMessage.error('配置切换失败: ' + error.message);
                // 错误时恢复原始配置选择
                await loadStatus();
            }
        };
        
        // 配置抽屉相关
        const openConfigDrawer = async () => {
            configDrawerVisible.value = true;
            await loadConfigs();
        };
        
        const closeConfigDrawer = () => {
            configDrawerVisible.value = false;
        };
        
        const loadConfigs = async () => {
            try {
                // 加载Claude配置
                const claudeData = await fetchWithErrorHandling('/api/config/claude');
                const claudeContent = claudeData?.content ?? '{}';
                configContents.claude = claudeContent.trim() ? claudeContent : '{}';
                
                // 加载Codex配置
                const codexData = await fetchWithErrorHandling('/api/config/codex');
                const codexContent = codexData?.content ?? '{}';
                configContents.codex = codexContent.trim() ? codexContent : '{}';
            } catch (error) {
                const errorMsg = '// 加载失败: ' + error.message;
                configContents.claude = errorMsg;
                configContents.codex = errorMsg;
            }
        };
        
        const saveConfig = async () => {
            const service = activeConfigTab.value;
            const content = configContents[service];
            
            if (!content.trim()) {
                ElMessage.warning('配置内容不能为空');
                return;
            }
            
            // 验证JSON格式
            try {
                JSON.parse(content);
            } catch (e) {
                ElMessage.error('JSON格式错误: ' + e.message);
                return;
            }
            
            configSaving.value = true;
            try {
                const result = await fetchWithErrorHandling(`/api/config/${service}`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({ content })
                });
                
                if (result.success) {
                    ElMessage.success(result.message || '配置保存成功');
                    await loadData();
                } else {
                    ElMessage.error('保存失败: ' + (result.error || '未知错误'));
                }
            } catch (error) {
                ElMessage.error('保存失败: ' + error.message);
            } finally {
                configSaving.value = false;
            }
        };
        
        // 过滤器抽屉相关
        const openFilterDrawer = async () => {
            filterDrawerVisible.value = true;
            await loadFilter();
        };
        
        // 添加过滤规则
        const addFilterRule = () => {
            filterRules.value.push({
                source: '',
                target: '',
                op: 'replace'
            });
        };
        
        // 删除过滤规则
        const removeFilterRule = (index) => {
            filterRules.value.splice(index, 1);
        };
        
        const closeFilterDrawer = () => {
            filterDrawerVisible.value = false;
        };
        
        const loadFilter = async () => {
            try {
                const data = await fetchWithErrorHandling('/api/filter');
                filterContent.value = data.content || '[]';
                
                // 解析JSON并转换为规则数组
                try {
                    let parsedRules = JSON.parse(filterContent.value);
                    if (!Array.isArray(parsedRules)) {
                        parsedRules = [parsedRules];
                    }
                    filterRules.value = parsedRules.map(rule => ({
                        source: rule.source || '',
                        target: rule.target || '',
                        op: rule.op || 'replace'
                    }));
                } catch (e) {
                    // 如果JSON解析失败，初始化为空数组
                    filterRules.value = [];
                }
            } catch (error) {
                filterRules.value = [];
                ElMessage.error('加载过滤规则失败: ' + error.message);
            }
        };
        
        const saveFilter = async () => {
            // 过滤掉空规则
            const validRules = filterRules.value.filter(rule => rule.source && rule.source.trim());
            
            if (validRules.length === 0) {
                const emptyRules = '[]';
                filterContent.value = emptyRules;
            } else {
                // 验证规则
                for (const rule of validRules) {
                    if (!['replace', 'remove'].includes(rule.op)) {
                        ElMessage.error('op 字段必须是 replace 或 remove');
                        return;
                    }
                    if (rule.op === 'replace' && !rule.target) {
                        ElMessage.error('replace 操作必须填写替换后的文本');
                        return;
                    }
                }
                
                // 转换为JSON格式
                const jsonRules = validRules.map(rule => {
                    const obj = {
                        source: rule.source,
                        op: rule.op
                    };
                    if (rule.op === 'replace') {
                        obj.target = rule.target || '';
                    }
                    return obj;
                });
                
                filterContent.value = JSON.stringify(jsonRules, null, 2);
            }
            
            filterSaving.value = true;
            try {
                const result = await fetchWithErrorHandling('/api/filter', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({ content: filterContent.value })
                });
                
                if (result.success) {
                    ElMessage.success(result.message || '过滤规则保存成功');
                    await loadData();
                } else {
                    ElMessage.error('保存失败: ' + (result.error || '未知错误'));
                }
            } catch (error) {
                ElMessage.error('保存失败: ' + error.message);
            } finally {
                filterSaving.value = false;
            }
        };
        
        // 工具方法
        const formatTimestamp = (timestamp) => {
            if (!timestamp) return '-';

            try {
                const date = new Date(timestamp);
                const year = date.getFullYear();
                const month = String(date.getMonth() + 1).padStart(2, '0');
                const day = String(date.getDate()).padStart(2, '0');
                const hours = String(date.getHours()).padStart(2, '0');
                const minutes = String(date.getMinutes()).padStart(2, '0');
                const seconds = String(date.getSeconds()).padStart(2, '0');

                return `${year}-${month}-${day} ${hours}:${minutes}:${seconds}`;
            } catch (e) {
                return timestamp;
            }
        };
        
        const truncatePath = (path) => {
            // 不截断URL，显示完整内容
            return path || '-';
        };
        
        const getStatusTagType = (statusCode) => {
            if (!statusCode) return '';
            
            const status = parseInt(statusCode);
            if (status >= 200 && status < 300) return 'success';
            if (status >= 400 && status < 500) return 'warning';
            if (status >= 500) return 'danger';
            return '';
        };
        
        // 日志详情相关方法
        const decodeBodyContent = (encodedContent) => {
            if (!encodedContent) {
                return '';
            }

            try {
                const decodedBytes = atob(encodedContent);
                const decodedText = decodeURIComponent(decodedBytes.split('').map(c =>
                    '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2)
                ).join(''));

                try {
                    const jsonObj = JSON.parse(decodedText);
                    return JSON.stringify(jsonObj, null, 2);
                } catch {
                    return decodedText;
                }
            } catch (error) {
                console.error('解码请求体失败:', error);
                return '解码失败: ' + error.message;
            }
        };

        const showLogDetail = (log) => {
            selectedLog.value = log;
            activeLogTab.value = 'basic'; // 重置到基本信息tab
            logDetailVisible.value = true;

            decodedRequestBody.value = decodeBodyContent(log.filtered_body);
            decodedOriginalRequestBody.value = decodeBodyContent(log.original_body);
            decodedResponseContent.value = decodeBodyContent(log.response_content);
        };
        
        // 加载所有日志
        const loadAllLogs = async () => {
            allLogsLoading.value = true;
            try {
                const data = await fetchWithErrorHandling('/api/logs/all');
                allLogs.value = Array.isArray(data) ? data : [];
            } catch (error) {
                ElMessage.error('获取所有日志失败: ' + error.message);
                allLogs.value = [];
            } finally {
                allLogsLoading.value = false;
            }
        };
        
        // 查看所有日志
        const viewAllLogs = async () => {
            allLogsVisible.value = true;
            await loadAllLogs();
        };
        
        // 刷新所有日志
        const refreshAllLogs = () => {
            loadAllLogs();
        };
        
        // 格式化请求体JSON
        const formatJsonContent = (bodyRef) => {
            if (!bodyRef.value) {
                ElMessage.warning('没有请求体内容');
                return;
            }

            try {
                const jsonObj = JSON.parse(bodyRef.value);
                bodyRef.value = JSON.stringify(jsonObj, null, 2);
                ElMessage.success('JSON格式化成功');
            } catch (error) {
                ElMessage.error('不是有效的JSON格式');
            }
        };

        const formatFilteredRequestBody = () => formatJsonContent(decodedRequestBody);
        const formatOriginalRequestBody = () => formatJsonContent(decodedOriginalRequestBody);
        const formatResponseContent = () => formatJsonContent(decodedResponseContent);
        
        
        // 对Headers按字母排序
        const getSortedHeaderKeys = (headers) => {
            if (!headers || typeof headers !== 'object') {
                return [];
            }
            return Object.keys(headers).sort((a, b) => {
                // 不区分大小写的字母排序
                return a.toLowerCase().localeCompare(b.toLowerCase());
            });
        };

        // 复制到剪贴板
        const copyToClipboard = async (text) => {
            try {
                await navigator.clipboard.writeText(text);
                ElMessage.success('已复制到剪贴板');
            } catch (error) {
                // 降级方案
                const textArea = document.createElement('textarea');
                textArea.value = text;
                textArea.style.position = 'fixed';
                textArea.style.opacity = '0';
                document.body.appendChild(textArea);
                textArea.select();
                try {
                    document.execCommand('copy');
                    ElMessage.success('已复制到剪贴板');
                } catch (err) {
                    ElMessage.error('复制失败');
                }
                document.body.removeChild(textArea);
            }
        };
        
        // 清空所有日志
        const clearAllLogs = async () => {
            try {
                await ElMessageBox.confirm(
                    '确定要清空所有日志吗？此操作不可撤销。',
                    '确认清空',
                    {
                        confirmButtonText: '确定',
                        cancelButtonText: '取消',
                        type: 'warning',
                    }
                );
                
                const result = await fetchWithErrorHandling('/api/logs', {
                    method: 'DELETE'
                });
                
                if (result.success) {
                    ElMessage.success('日志已清空');
                    // 刷新页面数据
                    window.location.reload();
                } else {
                    ElMessage.error('清空日志失败: ' + (result.error || '未知错误'));
                }
            } catch (error) {
                if (error !== 'cancel') {
                    ElMessage.error('清空日志失败: ' + error.message);
                }
            }
        };
        
        // 组件挂载
        onMounted(() => {
            loadData();
        });
        
        return {
            // 响应式数据
            loading,
            logsLoading,
            allLogsLoading,
            configSaving,
            filterSaving,
            lastUpdate,
            services,
            stats,
            logs,
            allLogs,
            claudeConfigs,
            codexConfigs,
            configDrawerVisible,
            filterDrawerVisible,
            logDetailVisible,
            allLogsVisible,
            activeConfigTab,
            activeLogTab,
            configContents,
            filterContent,
            filterRules,
            selectedLog,
            decodedRequestBody,
            decodedOriginalRequestBody,
            usageSummary,
            usageDrawerVisible,
            usageDetails,
            usageDetailsLoading,
            usageMetricLabels,
            metricKeys,
            
            // 方法
            refreshData,
            switchConfig,
            openConfigDrawer,
            closeConfigDrawer,
            saveConfig,
            openFilterDrawer,
            closeFilterDrawer,
            loadFilter,
            saveFilter,
            addFilterRule,
            removeFilterRule,
            formatTimestamp,
            truncatePath,
            getStatusTagType,
            showLogDetail,
            viewAllLogs,
            refreshAllLogs,
            clearAllLogs,
            copyToClipboard,
            formatFilteredRequestBody,
            formatOriginalRequestBody,
            formatResponseContent,
            decodedResponseContent,
            formatUsageValue,
            formatUsageSummary,
            getUsageFormattedValue,
            formatChannelName,
            formatServiceWithChannel,
            formatMethodWithURL,
            openUsageDrawer,
            closeUsageDrawer,
            clearUsageData,
            loadUsageDetails,
            getSortedHeaderKeys
        };
    }
});

// 使用Element Plus
app.use(ElementPlus);

// 挂载应用
app.mount('#app');

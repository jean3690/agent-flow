package com.agentflow.service;

import com.agentflow.entity.ExecutionNodeLog;
import com.agentflow.entity.ExecutionRecord;
import com.agentflow.mapper.ExecutionNodeLogMapper;
import com.agentflow.mapper.ExecutionRecordMapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.context.event.EventListener;
import org.springframework.stereotype.Component;

import java.time.Duration;
import java.time.LocalDateTime;
import java.util.List;

/**
 * 启动时修复上次进程遗留的 RUNNING 记录。
 *
 * <p>执行状态保存在内存的 {@code running} 映射里，进程被 kill 或崩溃后数据库中的
 * RUNNING 记录没有任何线程会再收尾，会永久停留在"运行中"并阻止删除、干扰统计。
 * 服务就绪后把这些记录统一置为 FAILED 并补齐耗时，同时收尾仍未结束的节点日志。
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class ExecutionRecoveryService {

    private static final String RUNNING = "RUNNING";
    private static final String FAILED = "FAILED";
    static final String INTERRUPTED_MESSAGE = "服务重启，执行中断（未收到终态）";

    private final ExecutionRecordMapper recordMapper;
    private final ExecutionNodeLogMapper nodeLogMapper;

    @EventListener(ApplicationReadyEvent.class)
    public void recoverOnStartup() {
        try {
            int recovered = recoverStaleExecutions();
            if (recovered > 0) {
                log.warn("recovered {} stale RUNNING execution(s) left by the previous process", recovered);
            }
        } catch (Exception ex) {
            log.error("stale execution recovery failed", ex);
        }
    }

    /** @return 被修复的执行记录数 */
    public int recoverStaleExecutions() {
        List<ExecutionRecord> stale = recordMapper.selectList(new LambdaQueryWrapper<ExecutionRecord>()
                .eq(ExecutionRecord::getStatus, RUNNING));
        if (stale.isEmpty()) {
            return 0;
        }
        LocalDateTime now = LocalDateTime.now();
        for (ExecutionRecord record : stale) {
            record.setStatus(FAILED);
            record.setErrorMessage(INTERRUPTED_MESSAGE);
            record.setFinishedAt(now);
            record.setElapsedMs(elapsedMillis(record.getStartedAt(), now));
            recordMapper.updateById(record);
            closeRunningNodes(record.getRunId(), now);
            log.info("stale execution recovered, runId={}, workflowId={}", record.getRunId(), record.getWorkflowId());
        }
        return stale.size();
    }

    private void closeRunningNodes(String runId, LocalDateTime now) {
        List<ExecutionNodeLog> nodes = nodeLogMapper.selectList(new LambdaQueryWrapper<ExecutionNodeLog>()
                .eq(ExecutionNodeLog::getRunId, runId)
                .eq(ExecutionNodeLog::getStatus, RUNNING));
        for (ExecutionNodeLog node : nodes) {
            node.setStatus(FAILED);
            node.setErrorMessage(INTERRUPTED_MESSAGE);
            node.setFinishedAt(now);
            node.setElapsedMs(elapsedMillis(node.getStartedAt(), now));
            nodeLogMapper.updateById(node);
        }
    }

    private long elapsedMillis(LocalDateTime startedAt, LocalDateTime now) {
        return startedAt == null ? 0L : Math.max(0L, Duration.between(startedAt, now).toMillis());
    }
}

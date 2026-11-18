package com.agentflow.service;

import com.agentflow.entity.WorkflowTrigger;
import com.agentflow.event.TriggerChangedEvent;
import jakarta.annotation.PreDestroy;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.context.event.EventListener;
import org.springframework.scheduling.concurrent.ThreadPoolTaskScheduler;
import org.springframework.scheduling.support.CronTrigger;
import org.springframework.stereotype.Component;

import java.time.ZoneId;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ScheduledFuture;

/** 把启用中的 CRON 触发器注册到调度器；触发器变更时增量刷新。 */
@Slf4j
@Component
@RequiredArgsConstructor
public class TriggerScheduler {

    private final TriggerService triggerService;
    @Qualifier("triggerTaskScheduler")
    private final ThreadPoolTaskScheduler scheduler;

    private final Map<Long, ScheduledFuture<?>> jobs = new ConcurrentHashMap<>();

    @EventListener(ApplicationReadyEvent.class)
    public void start() {
        for (WorkflowTrigger trigger : triggerService.enabledCronTriggers()) {
            schedule(trigger);
        }
        log.info("trigger scheduler started, {} cron job(s)", jobs.size());
    }

    @EventListener
    public void onChanged(TriggerChangedEvent event) {
        refresh(event.triggerId());
    }

    public void refresh(Long triggerId) {
        cancel(triggerId);
        WorkflowTrigger trigger = triggerService.find(triggerId);
        if (trigger == null || trigger.getEnabled() == null || trigger.getEnabled() != 1
                || !"CRON".equals(trigger.getType())
                || trigger.getCronExpression() == null || trigger.getCronExpression().isBlank()) {
            return;
        }
        schedule(trigger);
    }

    private void schedule(WorkflowTrigger trigger) {
        try {
            CronTrigger cron = new CronTrigger(
                    trigger.getCronExpression(), ZoneId.of(trigger.getTimezone()));
            ScheduledFuture<?> future = scheduler.schedule(
                    () -> triggerService.fireCron(trigger.getId()), cron);
            if (future != null) {
                jobs.put(trigger.getId(), future);
            }
            triggerService.refreshNextRun(trigger.getId());
            log.info("trigger {} scheduled: {} ({})", trigger.getId(),
                    trigger.getCronExpression(), trigger.getTimezone());
        } catch (Exception ex) {
            triggerService.markScheduleError(trigger.getId(), ex.getMessage());
        }
    }

    private void cancel(Long triggerId) {
        ScheduledFuture<?> future = jobs.remove(triggerId);
        if (future != null) {
            future.cancel(false);
        }
    }

    @PreDestroy
    public void stop() {
        jobs.keySet().forEach(this::cancel);
    }
}

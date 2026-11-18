package com.agentflow.service;

import com.agentflow.entity.SchedulerLock;
import com.agentflow.mapper.SchedulerLockMapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.stereotype.Service;

import java.time.Duration;
import java.time.LocalDateTime;
import java.util.UUID;

/**
 * 基于数据库的调度租约锁，让多实例部署时同一个 CRON 触发点只被派发一次。
 *
 * <p>不引入 Redis：先尝试原子 UPDATE 抢占过期租约，失败再 INSERT；主键冲突说明
 * 其他实例仍在租约内。租约到期后无需手动释放，避免进程崩溃留下死锁。
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class SchedulerLockService {

    private final SchedulerLockMapper mapper;
    private final String owner = UUID.randomUUID().toString().replace("-", "");

    /** 抢占锁；同一 lockKey 在租约期内只允许一个实例成功。 */
    public boolean tryAcquire(String lockKey, Duration lease) {
        LocalDateTime now = LocalDateTime.now();
        LocalDateTime expiresAt = now.plus(lease);
        int updated = mapper.update(null, new LambdaUpdateWrapper<SchedulerLock>()
                .set(SchedulerLock::getOwner, owner)
                .set(SchedulerLock::getExpiresAt, expiresAt)
                .eq(SchedulerLock::getLockKey, lockKey)
                .lt(SchedulerLock::getExpiresAt, now));
        if (updated > 0) {
            return true;
        }
        SchedulerLock lock = new SchedulerLock();
        lock.setLockKey(lockKey);
        lock.setOwner(owner);
        lock.setExpiresAt(expiresAt);
        lock.setCreatedAt(now);
        try {
            mapper.insert(lock);
            return true;
        } catch (DuplicateKeyException ex) {
            return false;
        }
    }

    /** 主动释放（正常路径不需要，租约到期会自动失效）。 */
    public void release(String lockKey) {
        mapper.delete(new LambdaQueryWrapper<SchedulerLock>()
                .eq(SchedulerLock::getLockKey, lockKey)
                .eq(SchedulerLock::getOwner, owner));
    }

    /** 清理过期租约，避免表无限增长。 */
    public int purgeExpired() {
        return mapper.delete(new LambdaQueryWrapper<SchedulerLock>()
                .lt(SchedulerLock::getExpiresAt, LocalDateTime.now()));
    }

    public String owner() {
        return owner;
    }
}

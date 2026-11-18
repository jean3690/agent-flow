package com.agentflow.service;

import com.agentflow.entity.SchedulerLock;
import com.agentflow.mapper.SchedulerLockMapper;
import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import org.apache.ibatis.builder.MapperBuilderAssistant;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.dao.DuplicateKeyException;

import java.time.Duration;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class SchedulerLockServiceTest {

    @Mock private SchedulerLockMapper mapper;

    @BeforeEach
    void setUp() {
        // LambdaUpdateWrapper 需要实体元数据缓存
        TableInfoHelper.initTableInfo(new MapperBuilderAssistant(new MybatisConfiguration(), ""),
                SchedulerLock.class);
    }

    @Test
    void insertSucceedsWhenNoLeaseExists() {
        when(mapper.update(any(), any())).thenReturn(0);
        when(mapper.insert(any(SchedulerLock.class))).thenReturn(1);

        SchedulerLockService service = new SchedulerLockService(mapper);
        assertThat(service.tryAcquire("cron:1", Duration.ofSeconds(10))).isTrue();

        ArgumentCaptor<SchedulerLock> captor = ArgumentCaptor.forClass(SchedulerLock.class);
        verify(mapper).insert(captor.capture());
        assertThat(captor.getValue().getLockKey()).isEqualTo("cron:1");
        assertThat(captor.getValue().getOwner()).isEqualTo(service.owner());
        assertThat(captor.getValue().getExpiresAt()).isAfter(captor.getValue().getCreatedAt());
    }

    @Test
    void expiredLeaseIsTakenOverWithoutInsert() {
        when(mapper.update(any(), any())).thenReturn(1);

        SchedulerLockService service = new SchedulerLockService(mapper);
        assertThat(service.tryAcquire("cron:1", Duration.ofSeconds(10))).isTrue();
        verify(mapper, org.mockito.Mockito.never()).insert(any(SchedulerLock.class));
    }

    @Test
    void duplicateKeyMeansAnotherInstanceHoldsTheLease() {
        when(mapper.update(any(), any())).thenReturn(0);
        when(mapper.insert(any(SchedulerLock.class))).thenThrow(new DuplicateKeyException("dup"));

        SchedulerLockService service = new SchedulerLockService(mapper);
        assertThat(service.tryAcquire("cron:1", Duration.ofSeconds(10))).isFalse();
    }

    @Test
    void purgeDeletesExpiredLeases() {
        when(mapper.delete(any())).thenReturn(2);

        SchedulerLockService service = new SchedulerLockService(mapper);
        assertThat(service.purgeExpired()).isEqualTo(2);
    }
}
package com.agentflow.service;

import com.agentflow.common.BizException;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class TriggerServiceTest {

    @Test
    void fiveFieldCronIsExpandedToSpringFormat() {
        assertThat(TriggerService.validateCron("0 9 * * *")).isEqualTo("0 0 9 * * *");
        assertThat(TriggerService.validateCron(" */5  *  * * * ")).isEqualTo("0 */5 * * * *");
    }

    @Test
    void sixFieldCronIsKept() {
        assertThat(TriggerService.validateCron("30 0 9 * * 1-5")).isEqualTo("30 0 9 * * 1-5");
    }

    @Test
    void invalidCronIsRejected() {
        assertThatThrownBy(() -> TriggerService.validateCron(""))
                .isInstanceOf(BizException.class);
        assertThatThrownBy(() -> TriggerService.validateCron("0 9 *"))
                .isInstanceOf(BizException.class);
        assertThatThrownBy(() -> TriggerService.validateCron("0 0 99 * * *"))
                .isInstanceOf(BizException.class);
    }
}

package com.agentflow.service;

import com.agentflow.config.AgentFlowProperties;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class CryptoServiceTest {

    private final CryptoService crypto = new CryptoService(new AgentFlowProperties());

    @Test
    void encryptThenDecryptRoundTrips() {
        String plain = "sk-test-abcdef123456";
        String stored = crypto.encrypt(plain);

        assertNotEquals(plain, stored);
        assertTrue(stored.startsWith("enc:v1:"));
        assertEquals(plain, crypto.decrypt(stored));
    }

    @Test
    void encryptIsRandomizedPerCall() {
        String plain = "sk-same-key";
        assertNotEquals(crypto.encrypt(plain), crypto.encrypt(plain));
    }

    @Test
    void legacyPlaintextPassesThrough() {
        String legacy = "sk-plain-text-key";
        assertEquals(legacy, crypto.decrypt(legacy));
        assertTrue(crypto.encrypt(legacy).startsWith("enc:v1:"));
    }

    @Test
    void blankValuesAreUntouched() {
        assertEquals("", crypto.encrypt(""));
        assertEquals(null, crypto.decrypt(null));
        assertThrows(IllegalStateException.class, () -> crypto.decrypt("enc:v1:not-base64!!"));
    }
}

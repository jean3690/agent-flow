package com.agentflow.service;

import com.agentflow.config.AgentFlowProperties;
import org.springframework.stereotype.Service;

import javax.crypto.Cipher;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;
import javax.crypto.spec.SecretKeySpec;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.util.Base64;

/**
 * 服务商 API Key 落库加密：AES-256-GCM，密文带 `enc:v1:` 前缀。
 * 历史明文（无前缀）按原样返回，下一次保存时会被重新加密。
 */
@Service
public class CryptoService {

    private static final String PREFIX = "enc:v1:";
    private static final int IV_LENGTH = 12;
    private static final int TAG_BITS = 128;

    private final SecretKey key;
    private final SecureRandom random = new SecureRandom();

    public CryptoService(AgentFlowProperties properties) {
        try {
            byte[] derived = MessageDigest.getInstance("SHA-256")
                    .digest(properties.getCrypto().getKey().getBytes(StandardCharsets.UTF_8));
            this.key = new SecretKeySpec(derived, "AES");
        } catch (Exception ex) {
            throw new IllegalStateException("初始化 Key 加密失败", ex);
        }
    }

    public String encrypt(String plain) {
        if (plain == null || plain.isBlank() || plain.startsWith(PREFIX)) {
            return plain;
        }
        try {
            byte[] iv = new byte[IV_LENGTH];
            random.nextBytes(iv);
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.ENCRYPT_MODE, key, new GCMParameterSpec(TAG_BITS, iv));
            byte[] cipherText = cipher.doFinal(plain.getBytes(StandardCharsets.UTF_8));
            byte[] out = ByteBuffer.allocate(IV_LENGTH + cipherText.length)
                    .put(iv).put(cipherText).array();
            return PREFIX + Base64.getEncoder().encodeToString(out);
        } catch (Exception ex) {
            throw new IllegalStateException("Key 加密失败", ex);
        }
    }

    public String decrypt(String stored) {
        if (stored == null || !stored.startsWith(PREFIX)) {
            return stored;
        }
        try {
            byte[] data = Base64.getDecoder().decode(stored.substring(PREFIX.length()));
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.DECRYPT_MODE, key, new GCMParameterSpec(TAG_BITS, data, 0, IV_LENGTH));
            byte[] plain = cipher.doFinal(data, IV_LENGTH, data.length - IV_LENGTH);
            return new String(plain, StandardCharsets.UTF_8);
        } catch (Exception ex) {
            throw new IllegalStateException("Key 解密失败（加密密钥是否变更过？）", ex);
        }
    }
}

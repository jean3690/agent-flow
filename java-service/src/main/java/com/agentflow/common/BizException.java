package com.agentflow.common;

import lombok.Getter;
import org.springframework.http.HttpStatus;

@Getter
public class BizException extends RuntimeException {

    private final int code;
    private final HttpStatus status;

    public BizException(String message) {
        this(4000, message, HttpStatus.BAD_REQUEST);
    }

    public BizException(int code, String message, HttpStatus status) {
        super(message);
        this.code = code;
        this.status = status;
    }

    public static BizException notFound(String message) {
        return new BizException(4040, message, HttpStatus.NOT_FOUND);
    }

    public static BizException unauthorized(String message) {
        return new BizException(4010, message, HttpStatus.UNAUTHORIZED);
    }
}

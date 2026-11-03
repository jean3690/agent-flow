package com.agentflow.controller;

import com.agentflow.common.ApiResponse;
import com.agentflow.dto.LoginRequest;
import com.agentflow.dto.LoginResponse;
import com.agentflow.dto.UserVO;
import com.agentflow.security.UserContext;
import com.agentflow.service.AuthService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/auth")
@RequiredArgsConstructor
public class AuthController {

    private final AuthService authService;

    @PostMapping("/login")
    public ApiResponse<LoginResponse> login(@Valid @RequestBody LoginRequest request) {
        return ApiResponse.ok(authService.login(request));
    }

    @GetMapping("/me")
    public ApiResponse<UserVO> me() {
        return ApiResponse.ok(authService.current(UserContext.require()));
    }
}

package com.agentflow.service;

import com.agentflow.common.BizException;
import com.agentflow.dto.LoginRequest;
import com.agentflow.dto.LoginResponse;
import com.agentflow.dto.UserVO;
import com.agentflow.entity.User;
import com.agentflow.mapper.UserMapper;
import com.agentflow.security.CurrentUser;
import com.agentflow.security.JwtService;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import lombok.RequiredArgsConstructor;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;

@Service
@RequiredArgsConstructor
public class AuthService {

    private final UserMapper userMapper;
    private final PasswordEncoder passwordEncoder;
    private final JwtService jwtService;

    public LoginResponse login(LoginRequest request) {
        User user = userMapper.selectOne(new LambdaQueryWrapper<User>().eq(User::getUsername, request.getUsername()));
        if (user == null || !passwordEncoder.matches(request.getPassword(), user.getPassword())) {
            throw BizException.unauthorized("用户名或密码错误");
        }
        String token = jwtService.issue(user.getId(), user.getUsername(), user.getRole());
        return new LoginResponse(token, UserVO.from(user));
    }

    public UserVO current(CurrentUser currentUser) {
        User user = userMapper.selectById(currentUser.id());
        if (user == null) {
            throw BizException.unauthorized("用户不存在");
        }
        return UserVO.from(user);
    }
}

package com.agentflow.dto;

import com.agentflow.entity.User;
import lombok.Builder;
import lombok.Data;

@Data
@Builder
public class UserVO {

    private Long id;
    private String username;
    private String nickname;
    private String role;
    private String avatar;

    public static UserVO from(User user) {
        return UserVO.builder()
                .id(user.getId())
                .username(user.getUsername())
                .nickname(user.getNickname())
                .role(user.getRole())
                .avatar(user.getAvatar())
                .build();
    }
}

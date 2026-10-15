package com.example.cricket.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;

/** Request to create a (demo) match. */
public record CreateMatchRequest(
        @NotBlank @Size(max = 128) String team1,
        @NotBlank @Size(max = 128) String team2) {
}

package com.example.cricket.dto;

import jakarta.validation.constraints.*;

/**
 * A single ball event. eventId is an optional idempotency key; when omitted
 * the server derives one from (match, inning, over, ball), so retried
 * submissions are still deduplicated.
 */
public record BallEventRequest(
        @Size(max = 64) String eventId,
        @Min(1) @Max(2) int inning,
        @Min(0) @Max(19) int over,
        @Min(1) @Max(6) int ball,
        @NotBlank @Size(max = 64) String striker,
        @Size(max = 64) String nonStriker,
        @NotBlank @Size(max = 64) String bowler,
        @Min(0) @Max(6) int runs,
        boolean wicket) {
}

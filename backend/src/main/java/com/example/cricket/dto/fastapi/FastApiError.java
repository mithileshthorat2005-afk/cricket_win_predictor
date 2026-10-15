package com.example.cricket.dto.fastapi;

import com.fasterxml.jackson.annotation.JsonProperty;

/** Error body returned by FastAPI: {"detail": "..."} */
public record FastApiError(
        @JsonProperty("detail") String detail) {
}

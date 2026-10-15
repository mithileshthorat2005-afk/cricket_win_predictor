package com.example.cricket.repository;

import com.example.cricket.model.Innings;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.Optional;

public interface InningsRepository extends JpaRepository<Innings, Long> {
    Optional<Innings> findByMatchIdAndInningNumber(Long matchId, int inningNumber);
}

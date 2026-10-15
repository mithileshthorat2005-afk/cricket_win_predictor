package com.example.cricket.repository;

import com.example.cricket.model.Delivery;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;
import java.util.Optional;

public interface DeliveryRepository extends JpaRepository<Delivery, Long> {
    /** Idempotency lookup: has this exact event already been accepted? */
    Optional<Delivery> findByMatchIdAndEventId(Long matchId, String eventId);

    List<Delivery> findByMatchIdAndInningsIdOrderByOverAscBallAsc(Long matchId, Long inningsId);
}

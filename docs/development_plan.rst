Development Plan
================

This document lays out a prioritized roadmap for bringing py-libp2p to parity with
`go-libp2p <https://github.com/libp2p/go-libp2p>`_. It complements the feature matrix
in the repository `README <https://github.com/libp2p/py-libp2p#feature-breakdown>`_
and is intended to guide contributors and reviewers.

Guiding principles
------------------

1. **Port before harness.** Use go-libp2p as the behavioral reference for core
   implementation work, then validate those ports with interop and test-plans once
   py-libp2p has the local machinery to exercise.
2. **Foundation first.** Transports, security, and connection/resource management are
   the substrate everything else depends on.
3. **NAT traversal is the highest-value usability gap.** Most real deployments sit
   behind NATs; without relay/hole-punching the stack is not production-usable.
4. **Align on async model early.** py-libp2p is Trio-based today, while the wider
   libp2p ecosystem and most Python users target asyncio. This decision blocks a lot
   of downstream work and should be settled rather than deferred.

Priority order
--------------

P0 — Go parity foundation
~~~~~~~~~~~~~~~~~~~~~~~~~

These are prerequisites for everything else and should land first. The emphasis is
porting the core Go implementation patterns into py-libp2p, not depending on Go nodes
as the first step.

1. **Fix stale documentation.**
   The README matrix and :doc:`introduction` still describe an older state (they mark
   kad-dht, discovery, relay, autonat, and identify-push as missing, and claim QUIC is
   "near completion"). Bring them in line with the actual code.
   *Status: done. Effort: low. Risk: none.*

2. **Connection manager — initial port landed.**
   ``libp2p.host.connmgr.BasicConnMgr`` ports the core go-libp2p model:
   low/high watermarks, grace and silence periods, peer tags, protected peers,
   decaying tags, forced trimming, disconnect cleanup, and optional ``new_host``
   wiring via network notifees. Focused unit coverage and real ``Swarm`` trimming
   coverage live in ``tests/core/host/connmgr/``. The manager also runs as a
   Trio service for periodic background trimming.

   Remaining parity work:

   * Revisit ranking once py-libp2p supports multiple connections per peer; the
     current swarm is still one connection per peer.
   * Decide whether emergency memory-pressure trimming belongs in this layer.
   *Status: in progress. Effort remaining: low. Risk: low.*

3. **Resource manager — foundation port started.**
   ``libp2p.host.resource_manager`` now provides the initial Go-style scope model:
   system and transient scopes, peer/protocol/service scopes, connection and stream
   management scopes, memory reservations with priority thresholds, scope spans,
   scoped statistics, rollback on failed reservations, and a null manager. ``new_host``
   and ``new_swarm`` accept an optional resource manager and expose it on the network.

   Remaining parity work:

   * Enforce connection and stream reservations inside the transport/swarm/muxer paths.
   * Add allowlist, per-peer/per-protocol/per-service limit configuration loaders, and
     autoscaled defaults.
   * Integrate relay-v2 resource accounting with the shared manager instead of only
     using relay-local reservation counters.
   * Add metrics/trace reporting once the observability layer exists.
   *Status: in progress. Effort remaining: high. Risk: medium. Depends on: connmgr.*

4. **Event bus and notifee alignment.**
   Promote connection/stream lifecycle notifications to a Go-style event surface so
   connection manager, resource manager, identify, AutoNAT, and observability can share
   the same host signals.
   *Effort: medium. Risk: low. Depends on: connmgr.*

5. **Async model decision.**
   Confirm whether the port continues on Trio or starts an asyncio migration before
   adding more transport and service ports.
   *Effort: medium. Risk: high.*

P1 — Interop validation harness
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Interop is still required for "done", but it follows the local Go-parity ports instead
of driving them.

6. **Stand up real go-libp2p interop tests.**
   ``tests/interop/go_libp2p/test_go_basic.py`` is an ``assert True`` placeholder; the
   rust/zig suites are the same. Replace with a real ping/identify matrix against
   go-libp2p so we have a trustworthy compatibility baseline as ports land.
   *Effort: medium. Risk: surfaces latent bugs — which is the point.*

7. **Repair the js-libp2p ping interop.**
   The js interop harness reports ping as "Not Working" (JS client aborts). Root-cause
   the yamux/multistream negotiation and make ping pass.
   *Effort: medium. Risk: medium (may reveal protocol deviations).*

8. **Wire interop into CI.**
   Add an opt-in CI job (dockerized go/js nodes) so regressions are caught continuously.

P2 — Core transports & security
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

These close the biggest functional gaps for users choosing py-libp2p for new projects.

9. **QUIC transport.**
   Implement ``libp2p-quic`` (quic-v1) on top of an async QUIC library. Unblocks
   WebTransport and WebRTC later, and is the modern default transport upstream.
   *Effort: high. Risk: medium. Depends on: async-model decision (P0).*

10. **TLS secure channel.**
   Implement ``libp2p-tls`` per the spec so Noise is not the only production security
   option (WebRTC/WebTransport also require TLS certs).
   *Effort: medium. Risk: low. Depends on: crypto/serialization completeness.*

11. **WebSocket transport.**
   Implement ``libp2p-websocket`` (ws/wss). Broadens reach to browser-hosted peers.
   *Effort: medium. Risk: low.*

P3 — NAT traversal
~~~~~~~~~~~~~~~~~~

The highest-impact end-user feature. Several pieces already exist as prototypes.

12. **Finish & verify AutoNAT.**
    ``libp2p/host/autonat/`` exists but is unproven against go-libp2p. Validate
    client/server mode and integrate its reachability signal into the address book.
    *Effort: medium. Risk: low. Depends on: event bus/notifee alignment (P0);
    validate through interop harness (P1).*

13. **Finish & verify circuit-relay-v2.**
    ``libp2p/relay/circuit_v2/`` is substantial but untested cross-impl. Validate
    relay/client/hop modes and fix gaps found by interop tests.
    *Effort: high. Risk: medium.*

14. **Hole punching + DCUtR.**
    Implement the hole-punching service and ``/libp2p/dcutr`` on top of AutoNAT and
    relay-v2. This completes the NAT-traversal story.
    *Effort: high. Risk: high. Depends on: 12, 13.*

P4 — Discovery completeness
~~~~~~~~~~~~~~~~~~~~~~~~~~

15. **Random-walk discovery.**
    Random-walk is the default discovery primitive for DHT-based peer discovery.
    *Effort: low. Risk: low. Depends on: kad-dht (P5).*

16. **Rendezvous discovery.**
    Implement ``/libp2p/rendezvous/1.0.0`` for rendezvous-based peer exchange.
    *Effort: medium. Risk: low.*

P5 — Routing & storage
~~~~~~~~~~~~~~~~~~~~~~

17. **Complete & verify kad-dht.**
    ``libp2p/kad_dht/`` is large but untested against go-libp2p. Validate peer routing,
    value store, provider store, and refresh behavior via test-plans.
    *Effort: high. Risk: medium. Depends on: interop harness (P1).*

18. **Content routing + delegated routing.**
    Expose the content-routing interface (put/get providers) backed by the DHT, plus a
    delegated (HTTP) client.
    *Effort: medium. Risk: low. Depends on: 15.*

19. **Records (IPNS / ``libp2p-record``).**
    Implement the IPNS record validator and record store used by the DHT.
    *Effort: medium. Risk: low. Depends on: 15.*

P6 — Observability & polish
~~~~~~~~~~~~~~~~~~~~~~~~~~~

20. **Metrics (Prometheus).**
    Expose swarm, resource-manager, and protocol metrics via a Prometheus endpoint.
    *Effort: medium. Risk: low.*

21. **Legacy cleanup & alignment.**
    Decide the fate of deprecated-in-upstream components (secio, plaintext/insecure,
    mplex) and align defaults with go-libp2p (noise + tls + yamux + quic).

Cross-cutting decisions
-----------------------

* **Async model (do first).** Confirm or migrate the Trio-based core. This is the
  highest-leverage decision: it affects the QUIC/TLS/WebSocket work and the ability to
  attract contributors used to asyncio.
* **Test-plans adoption.** For every P2–P5 module, add the corresponding
  `libp2p/test-plans` scenario so "done" is defined by cross-implementation success,
  not just internal unit tests.

Suggested ordering within a sprint
----------------------------------

Work can proceed in parallel once the P0 foundation ports are underway:

* One stream finishes connection manager integration, then ports resource manager (P0).
* A second stream builds the interop validation harness (P1).
* A third stream drives transports/security (P2), then NAT traversal (P3).
* A fourth stream drives kad-dht verification (P5) and discovery (P4).

The matrix in the README should be updated whenever a module's status changes.

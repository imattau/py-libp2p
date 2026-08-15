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
   kad-dht, discovery, relay, and autonat as missing and do not reflect the native
   QUIC v1 implementation). Bring them in line with the actual code.
   *Status: done. Effort: low. Risk: none.*

2. **Connection manager — initial port landed.**
   ``libp2p.host.connmgr.BasicConnMgr`` ports the core go-libp2p model:
   low/high watermarks, grace and silence periods, peer tags, protected peers,
   decaying tags, forced trimming, disconnect cleanup, and optional ``new_host``
   wiring via network notifees. Focused unit coverage and real ``Swarm`` trimming
   coverage live in ``tests/core/host/connmgr/``. The manager also runs as a
   Trio service for periodic background trimming.

   Multi-connection ranking and emergency memory-pressure trimming are deferred to
   the later connection/resource-management phase once those capabilities exist.
   *Status: done for the current one-connection-per-peer swarm. Effort remaining:
   deferred. Risk: low.*

3. **Resource manager — foundation port started.**
   ``libp2p.host.resource_manager`` now provides the initial Go-style scope model:
   system and transient scopes, peer/protocol/service scopes, connection and stream
   management scopes, memory reservations with priority thresholds, scope spans,
   scoped statistics, rollback on failed reservations, and a null manager. ``new_host``
   and ``new_swarm`` accept an optional resource manager and expose it on the network.
   Swarm connection and stream opens now reserve/release resources through the manager.
   The manager also supports allowlisted peers, per-peer/per-protocol/per-service
   limit configuration, and autoscaled default limit sets.
   Relay-v2 reservations and forwarded data also consume the shared ``relay``
   service scope and release their accounting on expiry or shutdown.

   Metrics and trace reporting are deferred to P6 observability.
   *Status: done for the current resource-management scope. Effort remaining:
   deferred. Risk: low.*

4. **Event bus and notifee alignment.**
   Promote connection/stream lifecycle notifications to a Go-style event surface so
   connection manager, resource manager, identify, AutoNAT, and observability can share
   the same host signals. The existing notifee surface now emits connection,
   disconnection, stream-open, stream-close, listen, and listen-close events from the
   swarm lifecycle, and ``libp2p.network.events.EventBus`` provides typed
   subscription/filter semantics for the same events. Pubsub now consumes typed
   connected/disconnected events directly and retains its existing peer queues.
   The connection manager also supports binding to the event bus for its
   connected/disconnected lifecycle input.

   Identify and AutoNAT lifecycle integration is deferred to P3 service completion;
   neither currently registers a lifecycle consumer. The current event surface,
   pubsub/connmgr consumers, ordering, and backpressure coverage are complete.
   *Status: done for current consumers. Effort remaining: deferred. Risk: low.*

5. **Async model decision.**
   Continue the Go-parity port on Trio. An asyncio migration can be reconsidered as a
   separate compatibility project, but it no longer blocks P0 implementation work.
   *Status: done. Effort: none. Risk: accepted.*

P2 — Core transports & security
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

These close the biggest functional gaps for users choosing py-libp2p for new projects.

P2 is now the active implementation priority. Interoperability validation is retained
for a later phase so external nodes verify native ports without becoming a development
dependency.

9. **QUIC transport.**
   Implement ``libp2p-quic`` (quic-v1) on top of ``aioquic``'s sans-I/O API, with
   Trio owning UDP I/O, timers, cancellation, and task scheduling. QUIC streams
   are used directly, without the existing security and muxer upgrade layers;
   libp2p peer identity is authenticated through the TLS 1.3 certificate.
   Start with QUIC v1 and defer draft-29 support.
   The native Trio implementation now covers listener/dialer lifecycle, TLS identity,
   direct QUIC streams, swarm integration, and QUIC v1 peer multiaddrs. Remaining
   work is interoperability validation and production hardening in P7.
   *Status: native implementation complete for the current scope; interop pending.
   Effort remaining: medium. Risk: medium.*

10. **TLS secure channel.**
   Implement ``libp2p-tls`` per the spec so Noise is not the only production security
   option (WebRTC/WebTransport also require TLS certs). The implementation now
   provides TLS 1.3 memory-BIO handshakes, libp2p certificate authentication,
   peer-ID pinning, and swarm multistream negotiation. Interoperability validation
   and production hardening remain pending.
   *Status: native implementation complete for the current scope; interop pending.
   Effort remaining: medium. Risk: medium.*

11. **WebSocket transport.**
   Implement ``libp2p-websocket`` (ws/wss) with Trio-native ``trio-websocket``
   (``wsproto`` sans-I/O underneath), preserving the project-wide Trio decision.
   Adapt binary WebSocket messages to the existing byte-stream connection contract,
   then retain the normal libp2p security and muxer upgrade path above the raw
   transport. Initial acceptance covers ``/ws`` and ``/wss`` multiaddrs, listener
   and dialer lifecycle, binary framing, and close/EOF behavior; browser and Go
   interoperability remain P7 validation work. The native Trio implementation now
   covers those transport and swarm integration requirements with explicit TLS
   context configuration for ``wss``.
   *Status: native implementation complete for the current scope; interop and
   production hardening pending. Effort remaining: medium. Risk: medium.*

P3 — NAT traversal
~~~~~~~~~~~~~~~~~~

The highest-impact end-user feature. Several pieces already exist as prototypes.

12. **Finish AutoNAT native implementation.**
    ``libp2p/host/autonat/`` provides an opt-in host service, bounded and
    address-aware server dial-back, concurrent client probing, observed-address
    persistence, stale-result expiry, and host lifecycle integration.
    Cross-implementation validation is deferred to P7.
    *Status: native implementation complete for the current scope; interop pending
    in P7. Effort remaining: medium. Risk: low.*

13. **Finish circuit-relay-v2 native implementation.**
    ``libp2p/relay/circuit_v2/`` provides native relay, client, reservation,
    voucher, framing, lifecycle, and resource-limit behavior. Cross-implementation
    validation is deferred to P7.
    *Status: native implementation complete for the current scope; interop pending
    in P7. Effort remaining: medium. Risk: medium.*

14. **Hole punching + DCUtR.**
    The native Trio service now implements bounded ``/libp2p/dcutr`` framing,
    CONNECT/SYNC coordination, relay-event activation, RTT synchronization,
    retries, and direct-connection replacement in the swarm. Remaining work is
    TCP simultaneous-open socket reuse and QUIC packet-level probing are now
    wired through the native transports. Remaining work is validation across
    real NAT topologies and P7 cross-implementation testing.
    *Status: coordination and connection upgrade complete for the current scope;
    transport hole punching and interop pending. Effort remaining: high. Risk:
    high. Depends on: 12, 13.*

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
    *Effort: high. Risk: medium. Depends on: interop harness (P7).*

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

22. **Multi-connection connection-manager parity.**
    Revisit per-peer ranking and emergency memory-pressure trimming after the swarm
    supports multiple simultaneous connections per peer and exposes the required
    resource-pressure signals.
    *Effort: medium. Risk: medium. Depends on: multi-connection swarm support.*

P7 — Interoperability validation
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Interop follows the native transport, security, and protocol ports. It is an external
compatibility check, not a runtime dependency or an implementation prerequisite.

23. **Stand up real go-libp2p interop tests.**
    The opt-in ``p2pd`` ping test lives in ``tests/interop/go_libp2p/`` and should be
    expanded into ping/identify matrices once the native P2–P5 work is ready.
    *Effort: medium. Risk: surfaces protocol deviations.*

24. **Repair the js-libp2p ping interop.**
    Root-cause the existing yamux/multistream negotiation failure and make ping pass.
    *Effort: medium. Risk: medium.*

25. **Wire interop into CI.**
    Add opt-in CI jobs for Go, JS, and other implementations after the harness is
    deterministic and environment-independent.
    *Effort: medium. Risk: low.*

Cross-cutting decisions
-----------------------

* **Async model (done).** The core remains Trio-based. QUIC will use a sans-I/O
  backend so the transport does not introduce an asyncio runtime dependency.
* **Test-plans adoption.** For every P2–P5 module, add the corresponding
  `libp2p/test-plans` scenario so "done" is defined by cross-implementation success,
  not just internal unit tests.

Suggested ordering within a sprint
----------------------------------

Work can proceed in parallel once the P0 foundation ports are underway:

* P0 foundation work is complete for the current one-connection-per-peer architecture.
* The active stream drives transports/security (P2), then NAT traversal (P3).
* A fourth stream drives kad-dht verification (P5) and discovery (P4).

The matrix in the README should be updated whenever a module's status changes.

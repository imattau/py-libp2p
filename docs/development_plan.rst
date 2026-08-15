Development Plan
================

This document lays out a prioritized roadmap for bringing py-libp2p to parity with
`go-libp2p <https://github.com/libp2p/go-libp2p>`_. It complements the feature matrix
in the repository `README <https://github.com/libp2p/py-libp2p#feature-breakdown>`_
and is intended to guide contributors and reviewers.

Guiding principles
------------------

1. **Interop before features.** A module only counts as done when it passes the
   formal `libp2p test-plans <https://github.com/libp2p/test-plans>`_ against another
   implementation (go-libp2p is the reference).
2. **Foundation first.** Transports, security, and connection/resource management are
   the substrate everything else depends on.
3. **NAT traversal is the highest-value usability gap.** Most real deployments sit
   behind NATs; without relay/hole-punching the stack is not production-usable.
4. **Align on async model early.** py-libp2p is Trio-based today, while the wider
   libp2p ecosystem and most Python users target asyncio. This decision blocks a lot
   of downstream work and should be settled rather than deferred.

Priority order
--------------

P0 — Baseline & correctness
~~~~~~~~~~~~~~~~~~~~~~~~~~~

These are prerequisites for everything else and should land first.

1. **Fix stale documentation.**
   The README matrix and :doc:`introduction` still describe an older state (they mark
   kad-dht, discovery, relay, autonat, and identify-push as missing, and claim QUIC is
   "near completion"). Bring them in line with the actual code.
   *Effort: low. Risk: none.*

2. **Stand up real go-libp2p interop tests.**
   ``tests/interop/go_libp2p/test_go_basic.py`` is an ``assert True`` placeholder; the
   rust/zig suites are the same. Replace with a real ping/identify matrix against
   go-libp2p so we have a trustworthy compatibility baseline before adding features.
   *Effort: medium. Risk: surfaces latent bugs — which is the point.*

3. **Repair the js-libp2p ping interop.**
   The js interop harness reports ping as "Not Working" (JS client aborts). Root-cause
   the yamux/multistream negotiation and make ping pass.
   *Effort: medium. Risk: medium (may reveal protocol deviations).*

4. **Wire interop into CI.**
   Add an opt-in CI job (dockerized go/js nodes) so regressions are caught continuously.

P1 — Core transports & security
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

These close the biggest functional gaps for users choosing py-libp2p for new projects.

5. **QUIC transport.**
   Implement ``libp2p-quic`` (quic-v1) on top of an async QUIC library. Unblocks
   WebTransport and WebRTC later, and is the modern default transport upstream.
   *Effort: high. Risk: medium. Depends on: async-model decision (P0).*

6. **TLS secure channel.**
   Implement ``libp2p-tls`` per the spec so Noise is not the only production security
   option (WebRTC/WebTransport also require TLS certs).
   *Effort: medium. Risk: low. Depends on: crypto/serialization completeness.*

7. **WebSocket transport.**
   Implement ``libp2p-websocket`` (ws/wss). Broadens reach to browser-hosted peers.
   *Effort: medium. Risk: low.*

P2 — Connection & resource management
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Upstream hosts always ship these; py-libp2p currently has neither.

8. **Connection manager.**
   Port ``BasicConnMgr`` (connection limits, trimming, backoff) into ``libp2p/host/``.
   *Effort: medium. Risk: low.*

9. **Resource manager.**
   Port the resource-manager (per-protocol, per-peer, per-scope limits). A minimal
   ``RelayResourceManager`` already exists in ``relay/circuit_v2/resources.py`` to build on.
   *Effort: high. Risk: medium. Depends on: connmgr.*

P3 — NAT traversal
~~~~~~~~~~~~~~~~~~

The highest-impact end-user feature. Several pieces already exist as prototypes.

10. **Finish & verify AutoNAT.**
    ``libp2p/host/autonat/`` exists but is unproven against go-libp2p. Validate
    client/server mode and integrate its reachability signal into the address book.
    *Effort: medium. Risk: low. Depends on: interop baseline (P0).*

11. **Finish & verify circuit-relay-v2.**
    ``libp2p/relay/circuit_v2/`` is substantial but untested cross-impl. Validate
    relay/client/hop modes and fix gaps found by interop tests.
    *Effort: high. Risk: medium.*

12. **Hole punching + DCUtR.**
    Implement the hole-punching service and ``/libp2p/dcutr`` on top of AutoNAT and
    relay-v2. This completes the NAT-traversal story.
    *Effort: high. Risk: high. Depends on: 10, 11.*

P4 — Discovery completeness
~~~~~~~~~~~~~~~~~~~~~~~~~~

13. **Random-walk discovery.**
    Random-walk is the default discovery primitive for DHT-based peer discovery.
    *Effort: low. Risk: low. Depends on: kad-dht (P5).*

14. **Rendezvous discovery.**
    Implement ``/libp2p/rendezvous/1.0.0`` for rendezvous-based peer exchange.
    *Effort: medium. Risk: low.*

P5 — Routing & storage
~~~~~~~~~~~~~~~~~~~~~~

15. **Complete & verify kad-dht.**
    ``libp2p/kad_dht/`` is large but untested against go-libp2p. Validate peer routing,
    value store, provider store, and refresh behavior via test-plans.
    *Effort: high. Risk: medium. Depends on: interop baseline (P0).*

16. **Content routing + delegated routing.**
    Expose the content-routing interface (put/get providers) backed by the DHT, plus a
    delegated (HTTP) client.
    *Effort: medium. Risk: low. Depends on: 15.*

17. **Records (IPNS / ``libp2p-record``).**
    Implement the IPNS record validator and record store used by the DHT.
    *Effort: medium. Risk: low. Depends on: 15.*

P6 — Observability & polish
~~~~~~~~~~~~~~~~~~~~~~~~~~~

18. **Event bus.**
    Promote the discovery-only event mechanism to a global event bus emitting
    connection/stream/protocol lifecycle events.
    *Effort: medium. Risk: low.*

19. **Metrics (Prometheus).**
    Expose swarm, resource-manager, and protocol metrics via a Prometheus endpoint.
    *Effort: medium. Risk: low.*

20. **Legacy cleanup & alignment.**
    Decide the fate of deprecated-in-upstream components (secio, plaintext/insecure,
    mplex) and align defaults with go-libp2p (noise + tls + yamux + quic).

Cross-cutting decisions
-----------------------

* **Async model (do first).** Confirm or migrate the Trio-based core. This is the
  highest-leverage decision: it affects the QUIC/TLS/WebSocket work and the ability to
  attract contributors used to asyncio.
* **Test-plans adoption.** For every P1–P5 module, add the corresponding
  `libp2p/test-plans` scenario so "done" is defined by cross-implementation success,
  not just internal unit tests.

Suggested ordering within a sprint
----------------------------------

Work can proceed in parallel once the interop baseline exists (P0):

* One stream drives transports/security (P1) → conn/resource mgmt (P2).
* A second stream drives NAT traversal (P3).
* A third stream drives kad-dht verification (P5) and discovery (P4).

The matrix in the README should be updated whenever a module's status changes.

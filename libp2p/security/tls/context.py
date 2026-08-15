from collections.abc import Callable

from OpenSSL import SSL

from .identity import TLSIdentity


def create_tls_context(
    identity: TLSIdentity,
    *,
    is_server: bool,
    verify_callback: Callable[..., bool] | None = None,
) -> SSL.Context:
    """
    Create a TLS 1.3 context for a libp2p identity.

    Certificate-chain trust is deliberately deferred to the libp2p certificate
    verifier. The callback keeps OpenSSL from rejecting self-signed peer
    certificates before that verifier can inspect the identity extension.
    """
    method = SSL.TLS_SERVER_METHOD if is_server else SSL.TLS_CLIENT_METHOD
    context = SSL.Context(method)
    context.set_min_proto_version(SSL.TLS1_3_VERSION)
    context.set_max_proto_version(SSL.TLS1_3_VERSION)
    context.use_certificate(identity.certificate)
    context.use_privatekey(identity.certificate_key)
    context.check_privatekey()
    context.set_alpn_protos([b"libp2p"])
    callback = verify_callback or (lambda *_args: True)
    verify_mode = SSL.VERIFY_PEER
    if is_server:
        verify_mode |= SSL.VERIFY_FAIL_IF_NO_PEER_CERT
    context.set_verify(verify_mode, callback)
    context.set_verify_depth(1)
    return context

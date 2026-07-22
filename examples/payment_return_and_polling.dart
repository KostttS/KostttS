enum PaymentState {
  succeeded,
  pending,
  canceled,
  failed,
  timedOut,
}

/// Verifies that an incoming deep link belongs to the expected application.
///
/// Add host and path checks when a project uses multiple deep-link routes.
bool isExpectedPaymentReturn(
  Uri uri, {
  required String expectedScheme,
  String? expectedHost,
}) {
  if (uri.scheme.toLowerCase() != expectedScheme.toLowerCase()) {
    return false;
  }

  if (expectedHost != null &&
      uri.host.toLowerCase() != expectedHost.toLowerCase()) {
    return false;
  }

  return true;
}

/// Polls a server-side payment-status endpoint.
///
/// [requestStatus] should call a trusted backend. Payment-provider secret keys
/// must never be stored in mobile application code.
Future<PaymentState> pollPaymentStatus({
  required Future<String> Function() requestStatus,
  int maxAttempts = 12,
  Duration interval = const Duration(seconds: 2),
}) async {
  for (var attempt = 0; attempt < maxAttempts; attempt++) {
    final state = _parsePaymentState(await requestStatus());

    if (state != PaymentState.pending) {
      return state;
    }

    if (attempt < maxAttempts - 1) {
      await Future<void>.delayed(interval);
    }
  }

  return PaymentState.timedOut;
}

PaymentState _parsePaymentState(String rawStatus) {
  switch (rawStatus.trim().toLowerCase()) {
    case 'succeeded':
    case 'success':
    case 'paid':
      return PaymentState.succeeded;
    case 'canceled':
    case 'cancelled':
      return PaymentState.canceled;
    case 'failed':
    case 'error':
      return PaymentState.failed;
    default:
      return PaymentState.pending;
  }
}

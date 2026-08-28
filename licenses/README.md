# Licensing

The Free edition of Mesh Sentinel is MIT licensed — see [../LICENSE](../LICENSE).

This directory is where the Pro licensing components will live once the Free
edition has passed the live test plan in [../docs/testing.md](../docs/testing.md).
Nothing is gated in 0.1.0.

The design constraints for Pro, recorded here so they are not quietly dropped
later:

* the licence key is validated locally;
* online verification is periodic and non-invasive;
* 14 days of full operation after the last successful verification;
* when a licence lapses, the Free edition keeps working — only Pro history,
  reports and extended correlation stop;
* **critical alerts never depend on the licence server.**

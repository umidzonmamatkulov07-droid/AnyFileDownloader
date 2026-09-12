globalThis.runInlineButtonBrowserTests = async function runInlineButtonBrowserTests() {
  const { equal } = globalThis.browserAssert;
  const fixture = document.createElement("div");
  fixture.id = "afd-inline-test-fixture";
  document.body.append(fixture);

  const sent = [];
  const controller = new AFDInlineButtons.InlineButtonController({
    document,
    MutationObserver,
    sendCandidate(candidate, done) {
      sent.push(candidate.url);
      done(true);
    }
  });
  controller.start();
  controller.setEnabled(false);

  const video = document.createElement("video");
  video.src = "https://media.example.test/first.mp4";
  Object.assign(video.style, { width: "320px", height: "180px", display: "block" });
  fixture.append(video);
  const videoCandidate = {
    url: video.src,
    detected_type: "VIDEO",
    evidence_strength: 3,
    source: "media_element"
  };
  controller.setCandidates([videoCandidate]);
  controller.refresh();
  equal(document.querySelectorAll("[data-afd-inline-button]").length, 0, "setting OFF disables insertion");

  controller.setEnabled(true);
  controller.refresh();
  equal(document.querySelectorAll("[data-afd-inline-button]").length, 1, "video button insertion");
  controller.refresh();
  equal(document.querySelectorAll("[data-afd-inline-button]").length, 1, "duplicate prevention");
  document.querySelector("[data-afd-inline-button]").click();
  equal(sent[0], videoCandidate.url, "video candidate association");

  const secondVideo = document.createElement("video");
  secondVideo.src = "https://media.example.test/dynamic.mp4";
  Object.assign(secondVideo.style, { width: "320px", height: "180px", display: "block" });
  fixture.append(secondVideo);
  controller.setCandidates([
    videoCandidate,
    { url: secondVideo.src, detected_type: "VIDEO", evidence_strength: 3, source: "media_element" }
  ]);
  controller.refresh();
  equal(document.querySelectorAll("[data-afd-inline-button]").length, 2, "dynamic media insertion");
  secondVideo.remove();
  controller.refresh();
  equal(document.querySelectorAll("[data-afd-inline-button]").length, 1, "stale media cleanup");

  video.getBoundingClientRect = () => ({
    width: 320, height: 180, top: -300, bottom: -120, left: 0, right: 320
  });
  controller.refresh();
  equal(document.querySelectorAll("[data-afd-inline-button]").length, 0, "offscreen media cleanup");
  video.getBoundingClientRect = () => ({
    width: 320, height: 180, top: 20, bottom: 200, left: 20, right: 340
  });
  controller.refresh();
  equal(document.querySelectorAll("[data-afd-inline-button]").length, 1, "visible media restoration");

  const anchor = document.createElement("a");
  anchor.href = "https://files.example.test/report.pdf";
  anchor.textContent = "Report";
  fixture.append(anchor);
  controller.setCandidates([
    videoCandidate,
    { url: anchor.href, detected_type: "DOCUMENT", evidence_strength: 1, source: "anchor_link" }
  ]);
  controller.refresh();
  equal(document.querySelectorAll("[data-afd-inline-button]").length, 2, "document link insertion");
  const anchorButton = anchor.nextElementSibling;
  anchorButton.click();
  equal(sent.at(-1), anchor.href, "document candidate association");

  controller.setEnabled(false);
  equal(document.querySelectorAll("[data-afd-inline-button]").length, 0, "setting toggle cleanup");
  controller.stop();
  fixture.remove();
};

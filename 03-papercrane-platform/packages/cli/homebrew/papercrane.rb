# Homebrew Formula stub for the Paper Crane CLI.
#
# Tap usage (once published):
#   brew tap papercrane/tap
#   brew install papercrane
#
# This stub is intentionally minimal — fill in `url` + `sha256` at release
# time from the GitHub release tarball, and bump `version` to match the npm
# package.

class Papercrane < Formula
  desc "Paper Crane CLI — submit binder design jobs from the terminal"
  homepage "https://papercrane.bio"
  url "https://github.com/papercrane-bio/papercrane/releases/download/v0.1.0/papercrane-cli-0.1.0.tgz"
  sha256 "0000000000000000000000000000000000000000000000000000000000000000"
  version "0.1.0"
  license "Apache-2.0"

  depends_on "node@20"

  def install
    system "npm", "install", "--omit=dev", *Language::Node.std_npm_install_args(libexec)
    bin.install_symlink Dir["#{libexec}/bin/papercrane"]
  end

  test do
    assert_match "papercrane", shell_output("#{bin}/papercrane --version")
  end
end

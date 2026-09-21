//go:build !windows

package usage

import "os"

func openReplaceableTranscript(path string) (*os.File, error) {
	return os.Open(path) //nolint:gosec // test-controlled path.
}

func replaceOpenTranscript(source, target string) error {
	return os.Rename(source, target)
}

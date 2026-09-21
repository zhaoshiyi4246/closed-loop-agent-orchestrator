//go:build windows

package importer

import (
	"errors"
	"path/filepath"
	"strings"

	"golang.org/x/sys/windows"
)

// Resolve the handle's real target for state roots which themselves use a
// Windows directory junction. Lexical comparisons cannot identify that alias.
func resolveImportFilesystemPath(path string) (string, error) {
	abs, err := filepath.Abs(path)
	if err != nil {
		return "", err
	}
	ptr, err := windows.UTF16PtrFromString(abs)
	if err != nil {
		return "", err
	}
	handle, err := windows.CreateFile(ptr, windows.FILE_READ_ATTRIBUTES,
		windows.FILE_SHARE_READ|windows.FILE_SHARE_WRITE|windows.FILE_SHARE_DELETE,
		nil, windows.OPEN_EXISTING, windows.FILE_FLAG_BACKUP_SEMANTICS, 0)
	if err != nil {
		return "", err
	}
	defer windows.CloseHandle(handle)
	size := uint32(256)
	for {
		buf := make([]uint16, size)
		n, err := windows.GetFinalPathNameByHandle(handle, &buf[0], size, 0)
		if err != nil {
			return "", err
		}
		if n < size {
			final := windows.UTF16ToString(buf[:n])
			if strings.HasPrefix(final, `\\?\UNC\`) {
				final = `\\` + strings.TrimPrefix(final, `\\?\UNC\`)
			} else {
				final = strings.TrimPrefix(final, `\\?\`)
			}
			return filepath.Clean(final), nil
		}
		size = n + 1
	}
}

// Git preparation must not traverse a junction into a protected state tree.
// Check each existing ancestor; EvalSymlinks alone is insufficient for all
// Windows reparse points. Unknown metadata is not permission to mutate.
func unsafeImportReparsePath(path string) bool {
	for current := filepath.Clean(path); ; current = filepath.Dir(current) {
		ptr, err := windows.UTF16PtrFromString(current)
		if err != nil {
			return true
		}
		attributes, err := windows.GetFileAttributes(ptr)
		if err != nil {
			if !errors.Is(err, windows.ERROR_FILE_NOT_FOUND) && !errors.Is(err, windows.ERROR_PATH_NOT_FOUND) {
				return true
			}
		} else if attributes&windows.FILE_ATTRIBUTE_REPARSE_POINT != 0 {
			return true
		}
		if filepath.Dir(current) == current {
			return false
		}
	}
}

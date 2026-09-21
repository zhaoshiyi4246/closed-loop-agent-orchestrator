//go:build !windows

package privatefile

import (
	"errors"
	"os"
)

func EnsureDirectory(path string) error {
	if err := os.Mkdir(path, 0o700); err != nil && !errors.Is(err, os.ErrExist) {
		return err
	}
	return ValidateDirectory(path)
}

func ValidateDirectory(path string) error {
	info, err := os.Lstat(path)
	if err != nil {
		return err
	}
	if !info.IsDir() || info.Mode()&os.ModeSymlink != 0 || info.Mode().Perm()&0o077 != 0 {
		return errors.New("private file: directory is not private")
	}
	return nil
}

func ValidateDirectoryPath(path string) error {
	info, err := os.Lstat(path)
	if err != nil {
		return err
	}
	if !info.IsDir() || info.Mode()&os.ModeSymlink != 0 {
		return errors.New("private file: directory is linked")
	}
	return nil
}

func ValidateFile(file *os.File) error {
	info, err := file.Stat()
	if err != nil {
		return err
	}
	if !info.Mode().IsRegular() || info.Mode().Perm()&0o077 != 0 {
		return errors.New("private file: file is not private")
	}
	return nil
}

func CopyPermissions(path string, target *os.File) error {
	info, err := os.Stat(path)
	if err != nil {
		return err
	}
	return target.Chmod(info.Mode().Perm())
}

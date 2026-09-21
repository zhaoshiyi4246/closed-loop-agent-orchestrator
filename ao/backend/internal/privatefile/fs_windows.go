//go:build windows

package privatefile

import (
	"errors"
	"fmt"
	"os"
	"unsafe"

	"golang.org/x/sys/windows"
)

func currentUserSID() (*windows.SID, error) {
	token, err := windows.OpenCurrentProcessToken()
	if err != nil {
		return nil, err
	}
	defer token.Close()
	user, err := token.GetTokenUser()
	if err != nil {
		return nil, err
	}
	return user.User.Sid.Copy()
}

func EnsureDirectory(path string) error {
	user, err := currentUserSID()
	if err != nil {
		return err
	}
	// Set the protected inheritable DACL at creation, before any source agent
	// can write a candidate. Do not repair permissions on pre-existing objects.
	sd, err := windows.SecurityDescriptorFromString("D:P(A;OICI;FA;;;" + user.String() + ")(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)")
	if err != nil {
		return err
	}
	name, err := windows.UTF16PtrFromString(path)
	if err != nil {
		return err
	}
	sa := windows.SecurityAttributes{Length: uint32(unsafe.Sizeof(windows.SecurityAttributes{})), SecurityDescriptor: sd}
	if err := windows.CreateDirectory(name, &sa); err != nil && !errors.Is(err, windows.ERROR_ALREADY_EXISTS) {
		return fmt.Errorf("private file: create private private directory: %w", err)
	}
	return ValidateDirectory(path)
}

func ValidateDirectory(path string) error {
	return inspectDirectory(path, true)
}

// ValidateDirectoryPath rejects reparse points without imposing an ACL policy
// on existing ancestors or source directories owned by the user.
func ValidateDirectoryPath(path string) error {
	return inspectDirectory(path, false)
}

func inspectDirectory(path string, private bool) error {
	name, err := windows.UTF16PtrFromString(path)
	if err != nil {
		return err
	}
	handle, err := windows.CreateFile(name, windows.READ_CONTROL, windows.FILE_SHARE_READ|windows.FILE_SHARE_WRITE|windows.FILE_SHARE_DELETE,
		nil, windows.OPEN_EXISTING, windows.FILE_FLAG_BACKUP_SEMANTICS|windows.FILE_FLAG_OPEN_REPARSE_POINT, 0)
	if err != nil {
		return fmt.Errorf("private file: inspect private directory security: %w", err)
	}
	defer windows.CloseHandle(handle)
	var info windows.ByHandleFileInformation
	if err := windows.GetFileInformationByHandle(handle, &info); err != nil {
		return err
	}
	if info.FileAttributes&windows.FILE_ATTRIBUTE_DIRECTORY == 0 || info.FileAttributes&windows.FILE_ATTRIBUTE_REPARSE_POINT != 0 {
		return errors.New("private file: private directory is not a real directory")
	}
	if private {
		return validateHandleSecurity(handle)
	}
	return nil
}

func ValidateFile(file *os.File) error {
	return validateHandleSecurity(windows.Handle(file.Fd()))
}

// CopyPermissions preserves an existing private object's DACL on a new private
// replacement. It never changes permissions on the existing source object.
func CopyPermissions(path string, target *os.File) error {
	source, err := os.Open(path)
	if err != nil {
		return err
	}
	defer source.Close()
	if err := ValidateFile(source); err != nil {
		return err
	}
	sd, err := windows.GetSecurityInfo(windows.Handle(source.Fd()), windows.SE_FILE_OBJECT, windows.DACL_SECURITY_INFORMATION)
	if err != nil {
		return err
	}
	dacl, _, err := sd.DACL()
	if err != nil {
		return err
	}
	control, _, err := sd.Control()
	if err != nil {
		return err
	}
	flags := windows.SECURITY_INFORMATION(windows.DACL_SECURITY_INFORMATION | windows.UNPROTECTED_DACL_SECURITY_INFORMATION)
	if control&windows.SE_DACL_PROTECTED != 0 {
		flags = windows.DACL_SECURITY_INFORMATION | windows.PROTECTED_DACL_SECURITY_INFORMATION
	}
	if err := windows.SetNamedSecurityInfo(target.Name(), windows.SE_FILE_OBJECT, flags, nil, nil, dacl, nil); err != nil {
		return err
	}
	return ValidateFile(target)
}

// App-owned private files may contain sensitive context. Only this account and the local
// system administrators may access them. This is an object ACL check, not a
// credential-vault policy or a claim that the contained text is sanitized.
func validateHandleSecurity(handle windows.Handle) error {
	user, err := currentUserSID()
	if err != nil {
		return err
	}
	sd, err := windows.GetSecurityInfo(handle, windows.SE_FILE_OBJECT, windows.OWNER_SECURITY_INFORMATION|windows.DACL_SECURITY_INFORMATION)
	if err != nil {
		return fmt.Errorf("private file: read private security: %w", err)
	}
	owner, _, err := sd.Owner()
	if err != nil || owner == nil || !owner.Equals(user) {
		return errors.New("private file: private owner is not the current user")
	}
	dacl, _, err := sd.DACL()
	if err != nil || dacl == nil {
		return errors.New("private file: private has no private DACL")
	}
	for index := uint32(0); index < uint32(dacl.AceCount); index++ {
		var ace *windows.ACCESS_ALLOWED_ACE
		if err := windows.GetAce(dacl, index, &ace); err != nil || ace == nil {
			return errors.New("private file: private DACL is unreadable")
		}
		if ace.Header.AceType == windows.ACCESS_DENIED_ACE_TYPE {
			continue
		}
		if ace.Header.AceType != windows.ACCESS_ALLOWED_ACE_TYPE {
			return errors.New("private file: private DACL has an unsupported entry")
		}
		sid := (*windows.SID)(unsafe.Pointer(&ace.SidStart))
		if !sid.Equals(user) && !sid.IsWellKnown(windows.WinLocalSystemSid) && !sid.IsWellKnown(windows.WinBuiltinAdministratorsSid) && !sid.IsWellKnown(windows.WinCreatorOwnerRightsSid) {
			return errors.New("private file: private DACL grants access to another principal")
		}
	}
	return nil
}

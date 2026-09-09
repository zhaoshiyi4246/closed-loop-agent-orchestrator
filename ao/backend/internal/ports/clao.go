package ports

import (
	"context"
	"errors"
	"strings"
)

type claoOwnerKey struct{}

// WithCLAOOwner is an in-process scheduling capability, never an HTTP field.
// Ordinary sessions do not require it. The verifier shares its mission's owner.
func WithCLAOOwner(ctx context.Context, id string) context.Context {
	return context.WithValue(ctx, claoOwnerKey{}, id)
}

func RequireCLAOOwner(ctx context.Context, sessionOwner string) error {
	if sessionOwner == "" {
		return nil
	}
	if id, _ := ctx.Value(claoOwnerKey{}).(string); id != "" && strings.TrimSuffix(sessionOwner, ":verifier") == id {
		return nil
	}
	return errors.New("此 Session 由 CLAO 闭环控制；不能单独恢复、重试或切换执行配置")
}
